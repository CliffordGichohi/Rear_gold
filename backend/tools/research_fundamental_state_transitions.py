from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from research_session_state_transitions import (
    FIVE_MINUTE_INSTRUMENT_SQL,
    Candidate,
    ManagedResult,
    _bars,
    _build_days,
    _build_signals,
    _cached_metrics,
    _compact_period_metrics,
    _portfolio_report,
    _simulate_all,
    _slice,
)

from gold_intel.application.fundamentals import (
    FundamentalInputs,
    load_fundamental_inputs,
)
from gold_intel.infrastructure.database import session_factory

Predicate = Callable[["FundamentalRecord"], bool]


@dataclass(frozen=True, slots=True)
class FundamentalRecord:
    managed: ManagedResult
    signed_score: float
    confidence: float
    coverage: float
    regime: str
    reaction_function: str
    event_risk: str
    minutes_to_catalyst: float | None
    crowding_percentile: float | None
    signed_components: dict[str, float | None]
    dominant_driver_aligned: bool
    event_age_hours: float | None

    @property
    def side_sign(self) -> int:
        return 1 if self.managed.signal.side == "LONG" else -1

    @property
    def core_confirmation_count(self) -> int:
        return sum(
            (self.signed_components.get(code) or 0.0) > 0
            for code in ("REAL_YIELD", "TWO_YEAR_YIELD", "USD")
        )

    @property
    def eurusd_aligned(self) -> bool:
        value = self.managed.signal.evidence.get("eurusd_60m_signed_atr")
        return value is not None and float(value) > 0

    @property
    def cot_not_crowded(self) -> bool:
        if self.crowding_percentile is None:
            return False
        if self.managed.signal.side == "LONG":
            return self.crowding_percentile < 90
        return self.crowding_percentile > 10

    @property
    def recent_event_aligned(self) -> bool:
        return (
            self.event_age_hours is not None
            and self.event_age_hours <= 8
            and _component(self, "CATALYST_SURPRISE") > 0
        )


@dataclass(frozen=True, slots=True)
class FundamentalRule:
    name: str
    minimum_discovery_trades: int
    predicate: Predicate


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
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
        fundamental_inputs = await load_fundamental_inputs(session, as_of=end)

    days = _build_days(gold_bars, start=start, end=end)
    signals = _build_signals(
        days,
        gold_bars=gold_bars,
        eurusd_bars=eurusd_bars,
    )
    managed = _simulate_all(signals, gold_bars=gold_bars)
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
    portfolios = {
        f"{cost_multiplier:.2f}x": _portfolio_report(
            selected,
            candidate_trades=candidate_trades,
            cost_multiplier=cost_multiplier,
        )
        for cost_multiplier in (1.0, 1.5)
    }
    report = {
        "contract": {
            "version": "FUNDAMENTAL_STATE_TRANSITION_V0_1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete_sessions": len(days),
            "signals": len(signals),
            "managed_results": len(managed),
            "fundamental_records": len(records),
            "candidate_hypotheses": len(candidates),
            "discovery": "2021-08-01 through 2022-12-31",
            "validation": "calendar year 2023",
            "forward_development": "calendar year 2024",
            "locked_holdout": "calendar year 2025 (not loaded)",
            "bulk_research_hashing": (
                "Per-signal provenance hashes are omitted because they do not "
                "affect any component, score, confidence, rule, or trade. A "
                "regression test requires the decision state to remain "
                "identical when hashing is disabled."
            ),
            "selection": (
                "Causal rules frozen before validation. General rules require "
                "40 discovery trades; post-event rules require 18. Discovery "
                "expectancy >=0.15R, PF>=1.20, 1.50x-cost expectancy >0.05R, "
                "bootstrap lower >=-0.05R; one candidate per archetype."
            ),
            "monthly_hurdle": (
                "All calendar months count. At 1% account risk, $1,000 on a "
                "$10,000 reference account requires approximately 10R/month."
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
                [
                    candidate
                    for candidate in candidates
                    if len(
                        _slice(
                            candidate_trades[(candidate.key, 1.0)],
                            "discovery",
                        )
                    )
                    >= next(
                        rule.minimum_discovery_trades
                        for rule in rules
                        if rule.name == candidate.rule
                    )
                ],
                key=lambda candidate: _ranking_key(
                    candidate,
                    candidate_trades=candidate_trades,
                ),
                reverse=True,
            )[: args.top]
        ],
        "portfolios": portfolios,
    }
    print(json.dumps(report, indent=2, sort_keys=True))


def _fundamental_records(
    managed: Sequence[ManagedResult],
    *,
    fundamental_inputs: FundamentalInputs,
) -> list[FundamentalRecord]:
    state_by_signal_time: dict[datetime, Any] = {}
    for result in managed:
        signal_time = result.signal.signal_time
        if signal_time not in state_by_signal_time:
            state_by_signal_time[signal_time] = fundamental_inputs.state_at(
                result.signal.signal_time,
                compute_data_hash=False,
            )

    output: list[FundamentalRecord] = []
    for result in managed:
        state = state_by_signal_time[result.signal.signal_time]
        side_sign = 1 if result.signal.side == "LONG" else -1
        signed_components = {
            component.code: (
                side_sign * component.direction
                if component.epistemic_status != "UNKNOWN"
                else None
            )
            for component in state.components
        }
        component_by_code = {
            component.code: component for component in state.components
        }
        dominant = component_by_code.get(state.dominant_driver)
        catalyst = component_by_code.get("CATALYST_SURPRISE")
        released_at_raw = (
            catalyst.evidence.get("released_at")
            if catalyst is not None
            and catalyst.epistemic_status != "UNKNOWN"
            else None
        )
        released_at = (
            datetime.fromisoformat(str(released_at_raw))
            if released_at_raw is not None
            else None
        )
        upcoming = state.upcoming_catalyst or {}
        crowding = state.reasoning.get("crowding", {})
        output.append(
            FundamentalRecord(
                managed=result,
                signed_score=side_sign * state.directional_score,
                confidence=state.confidence,
                coverage=state.coverage,
                regime=state.regime_label,
                reaction_function=state.reaction_function,
                event_risk=state.event_risk,
                minutes_to_catalyst=_optional_float(
                    upcoming.get("minutes_until")
                ),
                crowding_percentile=_optional_float(
                    crowding.get("percentile")
                ),
                signed_components=signed_components,
                dominant_driver_aligned=bool(
                    dominant is not None
                    and dominant.epistemic_status != "UNKNOWN"
                    and side_sign * dominant.direction > 0
                ),
                event_age_hours=(
                    (
                        result.signal.signal_time - released_at
                    ).total_seconds()
                    / 3600
                    if released_at is not None
                    else None
                ),
            )
        )
    return output


def _rules() -> tuple[FundamentalRule, ...]:
    return (
        FundamentalRule("BASE", 40, lambda record: True),
        FundamentalRule(
            "MACRO_NOT_OPPOSED_MINUS_5",
            40,
            lambda record: record.signed_score >= -5,
        ),
        FundamentalRule(
            "MACRO_ALIGNED_0",
            40,
            lambda record: record.signed_score >= 0,
        ),
        FundamentalRule(
            "MACRO_ALIGNED_10",
            40,
            lambda record: record.signed_score >= 10,
        ),
        FundamentalRule(
            "RATES_USD_2_OF_3",
            40,
            lambda record: record.core_confirmation_count >= 2,
        ),
        FundamentalRule(
            "MACRO_0_AND_RATES_USD_2_OF_3",
            40,
            lambda record: (
                record.signed_score >= 0
                and record.core_confirmation_count >= 2
            ),
        ),
        FundamentalRule(
            "MACRO_0_AND_INTRADAY_USD",
            40,
            lambda record: (
                record.signed_score >= 0 and record.eurusd_aligned
            ),
        ),
        FundamentalRule(
            "MACRO_5_AND_INTRADAY_USD",
            40,
            lambda record: (
                record.signed_score >= 5 and record.eurusd_aligned
            ),
        ),
        FundamentalRule(
            "DOMINANT_DRIVER_AND_INTRADAY_USD",
            40,
            lambda record: (
                record.dominant_driver_aligned and record.eurusd_aligned
            ),
        ),
        FundamentalRule(
            "REACTION_FUNCTION_ALIGNED",
            40,
            _reaction_function_aligned,
        ),
        FundamentalRule(
            "MACRO_0_AND_NOT_CROWDED",
            40,
            lambda record: (
                record.signed_score >= 0 and record.cot_not_crowded
            ),
        ),
        FundamentalRule(
            "EVENT_CLEAR_MACRO_0",
            40,
            lambda record: (
                record.event_risk in {"LOW", "ELEVATED"}
                and record.signed_score >= 0
            ),
        ),
        FundamentalRule(
            "POST_EVENT_SURPRISE_AND_USD",
            18,
            lambda record: (
                record.recent_event_aligned and record.eurusd_aligned
            ),
        ),
        FundamentalRule(
            "POST_EVENT_FULL_CAUSAL",
            18,
            lambda record: (
                record.recent_event_aligned
                and record.eurusd_aligned
                and record.signed_score >= -5
                and record.core_confirmation_count >= 1
            ),
        ),
        FundamentalRule(
            "FULL_CAUSAL_ALIGNMENT",
            30,
            lambda record: (
                record.signed_score >= 5
                and record.core_confirmation_count >= 2
                and record.eurusd_aligned
                and record.cot_not_crowded
                and (
                    record.event_risk in {"LOW", "ELEVATED"}
                    or record.recent_event_aligned
                )
            ),
        ),
    )


def _reaction_function_aligned(record: FundamentalRecord) -> bool:
    if not record.eurusd_aligned:
        return False
    focus = record.reaction_function
    if focus == "INFLATION_FOCUS":
        codes = (
            "INFLATION_REGIME",
            "REAL_YIELD",
            "TWO_YEAR_YIELD",
            "CATALYST_SURPRISE",
        )
    elif focus == "GROWTH_LABOUR_FOCUS":
        codes = (
            "GROWTH_REGIME",
            "LABOUR_REGIME",
            "TWO_YEAR_YIELD",
            "CATALYST_SURPRISE",
        )
    elif focus == "FINANCIAL_STRESS_FOCUS":
        codes = ("FINANCIAL_STRESS", "EQUITY_RISK", "REAL_YIELD", "USD")
    else:
        codes = ("REAL_YIELD", "TWO_YEAR_YIELD", "USD")
    return sum(_component(record, code) > 0 for code in codes) >= 2


def _candidate_results(
    records: Sequence[FundamentalRecord],
    *,
    rules: Sequence[FundamentalRule],
) -> tuple[list[Candidate], dict[tuple[str, float], list[Any]]]:
    archetypes = sorted(
        {record.managed.signal.playbook for record in records}
    )
    managers = sorted({record.managed.manager for record in records})
    candidates = [
        Candidate(
            archetype=archetype,
            rule=rule.name,
            manager=manager,
        )
        for archetype in archetypes
        for rule in rules
        for manager in managers
    ]
    rule_by_name = {rule.name: rule for rule in rules}
    output: dict[tuple[str, float], list[Any]] = {}
    for candidate in candidates:
        rule = rule_by_name[candidate.rule]
        for cost_multiplier in (1.0, 1.5):
            output[(candidate.key, cost_multiplier)] = [
                record.managed.trade
                for record in records
                if record.managed.signal.playbook == candidate.archetype
                and record.managed.manager == candidate.manager
                and record.managed.cost_multiplier == cost_multiplier
                and rule.predicate(record)
            ]
    return candidates, output


def _select_candidates(
    candidates: Sequence[Candidate],
    *,
    candidate_trades: dict[tuple[str, float], list[Any]],
    rules: Sequence[FundamentalRule],
) -> list[Candidate]:
    rule_by_name = {rule.name: rule for rule in rules}
    eligible = [
        candidate
        for candidate in candidates
        if _selectable(
            _slice(candidate_trades[(candidate.key, 1.0)], "discovery"),
            stressed=_slice(
                candidate_trades[(candidate.key, 1.5)],
                "discovery",
            ),
            minimum_trades=rule_by_name[
                candidate.rule
            ].minimum_discovery_trades,
        )
    ]
    by_archetype: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in eligible:
        by_archetype[candidate.archetype].append(candidate)
    selected = [
        max(
            members,
            key=lambda candidate: _ranking_key(
                candidate,
                candidate_trades=candidate_trades,
            ),
        )
        for members in by_archetype.values()
    ]
    return sorted(
        selected,
        key=lambda candidate: _ranking_key(
            candidate,
            candidate_trades=candidate_trades,
        ),
        reverse=True,
    )


def _selectable(
    trades: Sequence[Any],
    *,
    stressed: Sequence[Any],
    minimum_trades: int,
) -> bool:
    if len(trades) < minimum_trades or len(stressed) < minimum_trades:
        return False
    metrics = _cached_metrics(trades)
    stressed_metrics = _cached_metrics(stressed)
    interval = metrics.get("bootstrap_95ci")
    return bool(
        metrics["trades"] >= minimum_trades
        and metrics["net_expectancy_r"] is not None
        and float(metrics["net_expectancy_r"]) >= 0.15
        and metrics["profit_factor"] is not None
        and float(metrics["profit_factor"]) >= 1.20
        and stressed_metrics["net_expectancy_r"] is not None
        and float(stressed_metrics["net_expectancy_r"]) > 0.05
        and isinstance(interval, list)
        and float(interval[0]) >= -0.05
    )


def _candidate_report(
    candidate: Candidate,
    *,
    candidate_trades: dict[tuple[str, float], list[Any]],
    rules: Sequence[FundamentalRule],
) -> dict[str, Any]:
    rule = next(rule for rule in rules if rule.name == candidate.rule)
    base = candidate_trades[(candidate.key, 1.0)]
    stressed = candidate_trades[(candidate.key, 1.5)]
    return {
        "key": candidate.key,
        "minimum_discovery_trades": rule.minimum_discovery_trades,
        "selectable_on_discovery": _selectable(
            _slice(base, "discovery"),
            stressed=_slice(stressed, "discovery"),
            minimum_trades=rule.minimum_discovery_trades,
        ),
        "discovery": _compact_period_metrics(
            _slice(base, "discovery"),
            "discovery",
        ),
        "discovery_1_50x_cost": _compact_period_metrics(
            _slice(stressed, "discovery"),
            "discovery",
        ),
        "validation_2023": _compact_period_metrics(
            _slice(base, "validation"),
            "validation",
        ),
        "forward_2024": _compact_period_metrics(
            _slice(base, "forward"),
            "forward",
        ),
    }


def _ranking_key(
    candidate: Candidate,
    *,
    candidate_trades: dict[tuple[str, float], list[Any]],
) -> tuple[float, float, int]:
    metrics = _cached_metrics(
        _slice(candidate_trades[(candidate.key, 1.0)], "discovery")
    )
    expectancy = metrics["net_expectancy_r"]
    profit_factor = metrics["profit_factor"]
    return (
        float(expectancy) if expectancy is not None else -999.0,
        float(profit_factor) if profit_factor is not None else -999.0,
        int(metrics["trades"]),
    )


def _coverage_report(
    records: Sequence[FundamentalRecord],
) -> dict[str, Any]:
    unique: dict[int, FundamentalRecord] = {}
    for record in records:
        unique.setdefault(id(record.managed.signal), record)
    values = list(unique.values())
    by_year: dict[str, list[FundamentalRecord]] = defaultdict(list)
    for record in values:
        by_year[str(record.managed.signal.session_date.year)].append(record)
    return {
        "unique_signals": len(values),
        "reaction_functions": dict(
            sorted(Counter(record.reaction_function for record in values).items())
        ),
        "event_risk": dict(
            sorted(Counter(record.event_risk for record in values).items())
        ),
        "by_year": {
            year: {
                "signals": len(members),
                "average_coverage": round(
                    sum(member.coverage for member in members) / len(members),
                    3,
                ),
                "average_confidence": round(
                    sum(member.confidence for member in members) / len(members),
                    3,
                ),
                "post_event_signals": sum(
                    member.event_age_hours is not None
                    and member.event_age_hours <= 8
                    for member in members
                ),
            }
            for year, members in sorted(by_year.items())
        },
    }


def _component(record: FundamentalRecord, code: str) -> float:
    value = record.signed_components.get(code)
    return float(value) if value is not None else 0.0


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


if __name__ == "__main__":
    asyncio.run(main())
