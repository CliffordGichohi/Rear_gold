from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from research_cross_market_auction_micro_execution import (
    _five_minute_bars_from_csv_directory,
)
from research_multi_asset_session_portfolio import (
    CLUSTERS,
    COSTS,
    POINT_SIZES,
    _annual_gate,
    _coverage,
    _managed_results,
    _portfolio_report,
    _signal_funnel,
    _target_gate,
    _write_cache,
)
from research_multi_asset_trend_reversion import (
    LOCKED_HOLDOUT,
    _rules,
    _signals,
)
from research_session_state_transitions import (
    Candidate,
    ManagedResult,
    _candidate_report,
)

EXPECTED_INSTRUMENTS = frozenset(
    {
        "AUDUSD",
        "DE40",
        "GBPUSD",
        "USDJPY",
        "USTEC",
        "XTIUSD",
    }
)


@dataclass(frozen=True, slots=True)
class FrozenHypothesis:
    name: str
    family: str
    rule: str
    manager: str
    rationale: str


FROZEN_HYPOTHESES = (
    FrozenHypothesis(
        "DONCHIAN_RELATIVE_VOLUME_3R",
        "DONCHIAN_BREAKOUT",
        "RELATIVE_VOLUME_1_20X",
        "FIXED_3_00R",
        "Transferred from the stable EURUSD discovery/2023/2024 clue.",
    ),
    FrozenHypothesis(
        "FAILED_DONCHIAN_RELATIVE_VOLUME_3R",
        "FAILED_DONCHIAN",
        "RELATIVE_VOLUME_1_20X",
        "FIXED_3_00R",
        "Transferred from the stable EURUSD discovery/2023/2024 clue.",
    ),
    FrozenHypothesis(
        "COMPRESSION_TREND_240_4R",
        "COMPRESSION_BREAK",
        "TREND_240_ALIGNED",
        "FIXED_4_00R",
        "Transferred from the stable EURUSD discovery/2023/2024 clue.",
    ),
    FrozenHypothesis(
        "COMPRESSION_VOLATILITY_EXPANSION_2R",
        "COMPRESSION_BREAK",
        "VOLATILITY_EXPANSION",
        "FIXED_2_00R",
        "Transferred from the stable US500 discovery/2023/2024 clue.",
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate frozen structure hypotheses on untouched IC Markets "
            "instruments without parameter selection."
        ),
    )
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        metavar="INSTRUMENT=CSV_DIRECTORY",
    )
    parser.add_argument("--cache-output", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")
    if end > LOCKED_HOLDOUT:
        raise ValueError("The locked 2025 holdout must not be loaded")
    inputs = _parse_inputs(args.input)

    started = time.perf_counter()
    signals = []
    managed: list[ManagedResult] = []
    coverage: dict[str, Any] = {}
    manifests: dict[str, Any] = {}
    for instrument, directory in sorted(inputs.items()):
        bars = _five_minute_bars_from_csv_directory(
            directory,
            load_start=start - timedelta(days=12),
            load_end=end,
            point_size=POINT_SIZES[instrument],
        )
        instrument_signals = _signals(
            instrument,
            bars=bars,
            start=start,
            end=end,
        )
        signals.extend(instrument_signals)
        managed.extend(_managed_results(instrument_signals, bars=bars))
        coverage[instrument] = _coverage(bars)
        manifests[instrument] = _manifest(directory)
        _phase(f"{instrument}_COMPLETE", started)

    if args.cache_output is not None:
        _write_cache(managed, args.cache_output)
        _phase("CACHE_WRITTEN", started)

    candidates, candidate_trades = _frozen_candidate_results(managed)
    by_hypothesis: dict[str, Any] = {}
    for hypothesis in FROZEN_HYPOTHESES:
        members = _candidates_for_hypothesis(candidates, hypothesis)
        by_hypothesis[hypothesis.name] = _portfolio_bundle(
            members,
            candidate_trades=candidate_trades,
        )

    by_instrument = {
        instrument: _portfolio_bundle(
            [
                candidate
                for candidate in candidates
                if candidate.archetype.startswith(f"{instrument}|")
            ],
            candidate_trades=candidate_trades,
        )
        for instrument in sorted(inputs)
    }
    combined = [
        candidate
        for hypothesis in FROZEN_HYPOTHESES
        for candidate in _candidates_for_hypothesis(candidates, hypothesis)
    ]
    portfolio = _portfolio_bundle(
        combined,
        candidate_trades=candidate_trades,
    )
    report = {
        "contract": {
            "version": "CROSS_INSTRUMENT_FROZEN_TRANSFER_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "locked_holdout": "calendar year 2025 (not loaded)",
            "test_type": (
                "Cross-instrument transfer validation. Signal definitions, "
                "filters, target managers, sessions, and costs were declared "
                "before these six instruments were evaluated."
            ),
            "limitation": (
                "The instruments are untouched, but their timestamps overlap "
                "the source-market research period. Passing this test is not "
                "a substitute for the sealed calendar-2025 time holdout."
            ),
            "risk": (
                "One percent account risk equals 1R; at most two concurrent "
                "positions, no overlapping cluster exposure, and no new "
                "entry after -3R realized on the session date."
            ),
            "promotion": (
                "Positive expectancy in 2022, 2023, and 2024; positive at "
                "1.50x friction; positive median and at least 55% positive "
                "months in each period; diversified profit; and at least "
                "10R average per month in every period."
            ),
        },
        "frozen_hypotheses": [
            {
                "name": item.name,
                "family": item.family,
                "rule": item.rule,
                "manager": item.manager,
                "rationale": item.rationale,
            }
            for item in FROZEN_HYPOTHESES
        ],
        "data": {
            "provider": "IC_MARKETS_MT5",
            "environment": "DEMO",
            "timeframe": "observed 1m aggregated to complete 5m",
            "instruments": sorted(inputs),
            "coverage": coverage,
            "manifests": manifests,
        },
        "cost_model": {
            instrument: {
                "point_size": POINT_SIZES[instrument],
                "observed_spread": True,
                "slippage_per_side_price": COSTS[instrument].slippage_per_side,
                "round_turn_commission_price": (
                    COSTS[instrument].round_turn_commission_price
                ),
                "cluster": CLUSTERS[instrument],
            }
            for instrument in sorted(inputs)
        },
        "source_counts": {
            "signals": len(signals),
            "managed_executions": len(managed),
            "frozen_candidate_instances": len(candidates),
        },
        "signal_funnel": _signal_funnel(signals),
        "hypothesis_transfer_results": by_hypothesis,
        "instrument_transfer_results": by_instrument,
        "combined_frozen_portfolio": portfolio,
        "candidate_evidence": [
            _candidate_report(
                candidate,
                candidate_trades=candidate_trades,
            )
            for candidate in candidates
        ],
        "promotion_verdict": {
            "passed": bool(
                portfolio["positive_each_development_year"]["passed"]
                and portfolio["ten_r_monthly_promotion_gate"]["passed_screen"]
            ),
            "open_2025_holdout": bool(
                portfolio["positive_each_development_year"]["passed"]
                and portfolio["ten_r_monthly_promotion_gate"]["passed_screen"]
            ),
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.output is None:
        print(serialized)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": True,
                    "output": str(args.output),
                    "signals": len(signals),
                    "managed_executions": len(managed),
                    "promotion_passed": report["promotion_verdict"]["passed"],
                    "elapsed_seconds": report["elapsed_seconds"],
                },
                indent=2,
            ),
        )


def _parse_inputs(values: Sequence[str]) -> dict[str, Path]:
    output: dict[str, Path] = {}
    for value in values:
        instrument, separator, raw_directory = value.partition("=")
        instrument = instrument.strip().upper()
        directory = Path(raw_directory.strip())
        if not separator or not instrument or not raw_directory.strip():
            raise ValueError(f"Invalid --input value: {value!r}")
        if instrument in output:
            raise ValueError(f"Duplicate input instrument: {instrument}")
        if instrument not in EXPECTED_INSTRUMENTS:
            raise ValueError(f"Instrument is outside the frozen set: {instrument}")
        if not directory.is_dir():
            raise ValueError(f"CSV directory does not exist: {directory}")
        output[instrument] = directory
    missing = EXPECTED_INSTRUMENTS - output.keys()
    extra = output.keys() - EXPECTED_INSTRUMENTS
    if missing or extra:
        raise ValueError(
            f"Frozen input set mismatch; missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )
    return output


def _frozen_candidate_results(
    managed: Sequence[ManagedResult],
) -> tuple[list[Candidate], dict[tuple[str, float], list]]:
    archetypes = sorted({result.signal.playbook for result in managed})
    candidates = [
        Candidate(archetype, hypothesis.rule, hypothesis.manager)
        for hypothesis in FROZEN_HYPOTHESES
        for archetype in archetypes
        if archetype.rsplit("|", 1)[-1] == hypothesis.family
    ]
    by_scope: dict[tuple[str, str], list[Candidate]] = {}
    for candidate in candidates:
        by_scope.setdefault(
            (candidate.archetype, candidate.manager),
            [],
        ).append(candidate)
    rules = {rule.name: rule for rule in _rules()}
    output = {
        (candidate.key, multiplier): []
        for candidate in candidates
        for multiplier in (1.0, 1.5)
    }
    for result in managed:
        for candidate in by_scope.get(
            (result.signal.playbook, result.manager),
            [],
        ):
            if rules[candidate.rule].predicate(result.signal):
                output[(candidate.key, result.cost_multiplier)].append(result.trade)
    return candidates, output


def _candidates_for_hypothesis(
    candidates: Sequence[Candidate],
    hypothesis: FrozenHypothesis,
) -> list[Candidate]:
    return [
        candidate
        for candidate in candidates
        if candidate.archetype.rsplit("|", 1)[-1] == hypothesis.family
        and candidate.rule == hypothesis.rule
        and candidate.manager == hypothesis.manager
    ]


def _portfolio_bundle(
    candidates: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list],
) -> dict[str, Any]:
    base = _portfolio_report(
        candidates,
        candidate_trades=candidate_trades,
        cost_multiplier=1.0,
    )
    stressed = _portfolio_report(
        candidates,
        candidate_trades=candidate_trades,
        cost_multiplier=1.5,
    )
    return {
        "base_cost": base,
        "cost_stress_1_50x": stressed,
        "positive_each_development_year": _annual_gate(
            candidates,
            candidate_trades=candidate_trades,
        ),
        "ten_r_monthly_promotion_gate": _target_gate(base, stressed),
    }


def _manifest(directory: Path) -> dict[str, Any]:
    files = sorted(directory.glob("*.csv"))
    return {
        "directory": str(directory),
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "first_file": files[0].name if files else None,
        "last_file": files[-1].name if files else None,
    }


def _phase(name: str, started: float) -> None:
    print(
        f"{name} elapsed={time.perf_counter() - started:.3f}s",
        flush=True,
        file=__import__("sys").stderr,
    )


if __name__ == "__main__":
    main()
