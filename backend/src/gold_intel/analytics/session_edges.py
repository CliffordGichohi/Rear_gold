from __future__ import annotations

import hashlib
import json
import random
import statistics
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from gold_intel.analytics.fundamentals import FundamentalState

SESSION_EDGE_RULESET_VERSION = "LONDON_SWEEP_RECLAIM_V0_1"
SESSION_EDGE_SUMMARY_VERSION = "SESSION_EDGE_COHORT_SUMMARY_V0_2"

TOKYO = ZoneInfo("Asia/Tokyo")
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")

Side = Literal["LONG", "SHORT"]
BiasAlignment = Literal[
    "ALIGNED",
    "OPPOSED",
    "NEUTRAL",
    "INSUFFICIENT_FUNDAMENTALS",
    "UNKNOWN",
    "NOT_APPLICABLE",
]


@dataclass(frozen=True, slots=True)
class SessionEdgeBar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: float | None
    available_at: datetime
    spread_price: float | None = None
    source_record_key: str | None = None


@dataclass(frozen=True, slots=True)
class SessionEdgeFiveMinuteBar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: float | None
    spread_price: float | None
    available_at: datetime
    complete: bool


@dataclass(frozen=True, slots=True)
class SessionEdgeConfig:
    asia_start_local: str = "10:05"
    asia_end_local: str = "16:00"
    london_start_local: str = "08:00"
    london_end_local: str = "12:00"
    fundamental_freeze_minutes_before: int = 5
    atr_lookback_bars: int = 14
    compression_lookback_sessions: int = 20
    compression_min_history: int = 10
    compression_threshold_percentile: float = 50.0
    sweep_min_atr: float = 0.02
    sweep_max_atr: float = 0.75
    reclaim_bars: int = 2
    displacement_bars_after_reclaim: int = 3
    micro_structure_lookback_bars: int = 3
    displacement_min_body_atr: float = 0.35
    displacement_min_body_ratio: float = 0.60
    displacement_min_close_location: float = 0.70
    liquidity_lookback_bars: int = 100
    stop_buffer_atr: float = 0.10
    fundamental_min_score: float = 5.0
    fundamental_min_coverage: float = 35.0
    fundamental_min_confidence: float = 25.0
    outcome_horizons_minutes: tuple[int, ...] = (30, 60, 120, 240)
    target_r_levels: tuple[float, ...] = (0.50, 0.75, 1.00, 2.00)


@dataclass(frozen=True, slots=True)
class AsiaRange:
    session_date: date
    start_time: datetime
    end_time: datetime
    status: str
    bar_count: int
    expected_bar_count: int
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    range_size: float | None


@dataclass(frozen=True, slots=True)
class SweepAttempt:
    side: Side
    level_code: str
    level: float
    sweep_time: datetime
    sweep_extreme: float
    depth_price: float
    depth_atr: float
    qualified: bool
    qualification_reason: str
    reclaim_time: datetime | None
    micro_structure_level: float | None
    displacement_time: datetime | None
    displacement_body_atr: float | None
    displacement_body_ratio: float | None
    displacement_close_location: float | None
    tick_volume_percentile: float | None
    spread_percentile: float | None
    triggered: bool


@dataclass(frozen=True, slots=True)
class PathOutcome:
    horizon_minutes: int
    status: str
    bar_count: int
    expected_bar_count: int
    terminal_price: float | None
    terminal_return_pct: float | None
    terminal_r: float | None
    mfe_price: float | None
    mae_price: float | None
    mfe_r: float | None
    mae_r: float | None
    target_before_stop: dict[str, bool | None]
    gross_path_outcome_r_1r: float | None


@dataclass(frozen=True, slots=True)
class SessionOpportunity:
    session_date: date
    fundamental_freeze_time: datetime
    level_freeze_time: datetime
    london_start_time: datetime
    london_end_time: datetime
    status: str
    no_trigger_reason: str | None
    asia_range: AsiaRange
    asia_range_percentile: float | None
    asia_compression_state: str
    reference_levels: dict[str, float | None]
    fundamental: dict[str, Any]
    attempts: tuple[SweepAttempt, ...]
    setup_side: Side | None
    signal_time: datetime | None
    entry_time: datetime | None
    entry_reference_price: float | None
    invalidation_price: float | None
    risk_distance: float | None
    bias_alignment: BiasAlignment
    outcomes: tuple[PathOutcome, ...]
    data_hash: str
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SessionEdgeStudyResult:
    strategy: str
    opportunities: tuple[SessionOpportunity, ...]
    summary: dict[str, Any]
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _AtrIndex:
    close_times: tuple[datetime, ...]
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class _LevelSummary:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class _ReferenceLevelIndex:
    trading_dates: tuple[date, ...]
    trading_days: dict[date, _LevelSummary]
    trading_weeks: dict[tuple[int, int], _LevelSummary]


def london_session_clocks(
    session_date: date,
    config: SessionEdgeConfig,
) -> dict[str, datetime]:
    asia_start = _parse_clock(config.asia_start_local, "asia_start_local")
    asia_end = _parse_clock(config.asia_end_local, "asia_end_local")
    london_start = _parse_clock(config.london_start_local, "london_start_local")
    london_end = _parse_clock(config.london_end_local, "london_end_local")
    return {
        "asia_start": datetime.combine(session_date, asia_start, tzinfo=TOKYO).astimezone(UTC),
        "asia_end": datetime.combine(session_date, asia_end, tzinfo=TOKYO).astimezone(UTC),
        "fundamental_freeze": (
            datetime.combine(session_date, london_start, tzinfo=LONDON)
            - timedelta(minutes=config.fundamental_freeze_minutes_before)
        ).astimezone(UTC),
        "london_start": datetime.combine(session_date, london_start, tzinfo=LONDON).astimezone(UTC),
        "london_end": datetime.combine(session_date, london_end, tzinfo=LONDON).astimezone(UTC),
    }


def aggregate_session_edge_five_minutes(
    bars: Sequence[SessionEdgeBar],
    *,
    study_as_of: datetime,
) -> tuple[SessionEdgeFiveMinuteBar, ...]:
    """Build point-in-time five-minute bars from the earliest one-minute version.

    A bucket is complete only when all five expected minutes were available by
    the bucket close. A historical revision arriving later cannot repair an
    earlier decision clock.
    """

    if study_as_of.tzinfo is None:
        raise ValueError("study_as_of must include a timezone")
    canonical: dict[datetime, SessionEdgeBar] = {}
    for bar in sorted(bars, key=lambda item: (item.open_time, item.available_at)):
        if bar.close_time <= study_as_of and bar.available_at <= study_as_of:
            canonical.setdefault(bar.open_time.astimezone(UTC), bar)

    buckets: dict[datetime, list[SessionEdgeBar]] = defaultdict(list)
    for open_time, bar in canonical.items():
        bucket = open_time.replace(
            minute=open_time.minute - open_time.minute % 5,
            second=0,
            microsecond=0,
        )
        buckets[bucket].append(bar)

    output: list[SessionEdgeFiveMinuteBar] = []
    for bucket, members in sorted(buckets.items()):
        members.sort(key=lambda item: item.open_time)
        close_time = bucket + timedelta(minutes=5)
        expected = {bucket + timedelta(minutes=offset) for offset in range(5)}
        actual = {item.open_time.astimezone(UTC) for item in members}
        complete = (
            len(members) == 5
            and actual == expected
            and all(
                item.close_time <= close_time and item.available_at <= close_time
                for item in members
            )
        )
        volumes = [item.tick_volume for item in members]
        spreads = [item.spread_price for item in members if item.spread_price is not None]
        output.append(
            SessionEdgeFiveMinuteBar(
                open_time=bucket,
                close_time=close_time,
                open=members[0].open,
                high=max(item.high for item in members),
                low=min(item.low for item in members),
                close=members[-1].close,
                tick_volume=(
                    sum(float(value) for value in volumes if value is not None)
                    if volumes and all(value is not None for value in volumes)
                    else None
                ),
                spread_price=max(spreads) if spreads else None,
                available_at=max(item.available_at for item in members),
                complete=complete,
            )
        )
    return tuple(output)


def build_london_session_opportunities(
    bars: Sequence[SessionEdgeBar],
    *,
    start: datetime,
    end: datetime,
    config: SessionEdgeConfig | None = None,
    fundamental_state_at: Callable[[datetime], FundamentalState] | None = None,
) -> SessionEdgeStudyResult:
    """Create one immutable opportunity record for each complete London session."""

    selected_config = config or SessionEdgeConfig()
    _validate_inputs(bars, start=start, end=end, config=selected_config)
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    five_minute = aggregate_session_edge_five_minutes(bars, study_as_of=end_utc)
    bars_by_open = {bar.open_time: bar for bar in five_minute}
    global_indices = {bar.open_time: index for index, bar in enumerate(five_minute)}
    atr_index = _build_atr_index(
        five_minute,
        window=selected_config.atr_lookback_bars,
    )
    reference_level_index = _build_reference_level_index(five_minute)
    asia_ranges = _build_asia_ranges(
        five_minute,
        start_date=min(bar.open_time.astimezone(TOKYO).date() for bar in five_minute),
        end_date=end_utc.astimezone(TOKYO).date(),
        config=selected_config,
    )
    opportunities: list[SessionOpportunity] = []
    for session_date in _requested_session_dates(start_utc, end_utc, selected_config):
        clocks = london_session_clocks(session_date, selected_config)
        asia = asia_ranges.get(session_date) or _empty_asia_range(session_date, clocks)
        prior_ranges = [
            item.range_size
            for item_date, item in sorted(asia_ranges.items())
            if item_date < session_date
            and item.status == "COMPLETE"
            and item.range_size is not None
        ][-selected_config.compression_lookback_sessions :]
        range_percentile = (
            _percentile_rank(asia.range_size, prior_ranges)
            if len(prior_ranges) >= selected_config.compression_min_history
            else None
        )
        compression_state = (
            "UNKNOWN"
            if range_percentile is None
            else "COMPRESSED"
            if range_percentile <= selected_config.compression_threshold_percentile
            else "NOT_COMPRESSED"
        )
        fundamental_state = (
            fundamental_state_at(clocks["fundamental_freeze"])
            if fundamental_state_at is not None
            else None
        )
        fundamental = _fundamental_payload(
            fundamental_state,
            freeze_time=clocks["fundamental_freeze"],
        )
        reference_levels = _reference_levels(
            reference_level_index,
            freeze_time=clocks["london_start"],
        )
        if asia.high is not None and asia.low is not None:
            reference_levels.update(
                {
                    "ASIA_HIGH": asia.high,
                    "ASIA_LOW": asia.low,
                    "ASIA_MIDPOINT": (asia.high + asia.low) / 2,
                }
            )

        london_expected = _expected_five_minute_opens(
            clocks["london_start"],
            clocks["london_end"],
        )
        london_bars = [
            bars_by_open[open_time]
            for open_time in london_expected
            if open_time in bars_by_open and bars_by_open[open_time].complete
        ]
        session_atr = _atr_before(
            atr_index,
            before=clocks["london_start"],
        )
        base_evidence = {
            "ruleset_version": SESSION_EDGE_RULESET_VERSION,
            "epistemic_contract": {
                "levels_and_bars": "OBSERVED_OR_CALCULATED",
                "sweep_interpretation": "INFERRED",
                "outcomes": "CALCULATED",
            },
            "london_expected_bars": len(london_expected),
            "london_complete_bars": len(london_bars),
            "session_atr": session_atr,
            "prior_complete_asia_ranges": len(prior_ranges),
        }
        if (
            asia.status != "COMPLETE"
            or len(london_bars) != len(london_expected)
            or session_atr is None
            or session_atr <= 0
        ):
            reason = (
                "ASIA_RANGE_INCOMPLETE"
                if asia.status != "COMPLETE"
                else "LONDON_WINDOW_INCOMPLETE"
                if len(london_bars) != len(london_expected)
                else "ATR_WARMUP_INSUFFICIENT"
            )
            opportunity = _opportunity_without_trigger(
                session_date=session_date,
                clocks=clocks,
                status="INCOMPLETE_SESSION",
                reason=reason,
                asia=asia,
                range_percentile=range_percentile,
                compression_state=compression_state,
                reference_levels=reference_levels,
                fundamental=fundamental,
                evidence=base_evidence,
                config=selected_config,
            )
            opportunities.append(opportunity)
            continue

        attempts = _detect_sweep_attempts(
            five_minute,
            global_indices=global_indices,
            london_bars=london_bars,
            asia=asia,
            atr=session_atr,
            config=selected_config,
        )
        triggered = sorted(
            (attempt for attempt in attempts if attempt.triggered),
            key=lambda item: (
                item.displacement_time or datetime.max.replace(tzinfo=UTC),
                item.side,
            ),
        )
        if not triggered:
            status = _attempt_status(attempts)
            opportunity = _opportunity_without_trigger(
                session_date=session_date,
                clocks=clocks,
                status=status,
                reason=status,
                asia=asia,
                range_percentile=range_percentile,
                compression_state=compression_state,
                reference_levels=reference_levels,
                fundamental=fundamental,
                evidence=base_evidence,
                config=selected_config,
                attempts=attempts,
            )
            opportunities.append(opportunity)
            continue

        primary = triggered[0]
        if primary.displacement_time is None:  # pragma: no cover - guaranteed by triggered
            raise RuntimeError("Triggered attempt has no displacement time")
        displacement_bar = bars_by_open[primary.displacement_time - timedelta(minutes=5)]
        entry_time = primary.displacement_time
        entry_bar = bars_by_open.get(entry_time)
        invalidation = (
            primary.sweep_extreme - selected_config.stop_buffer_atr * session_atr
            if primary.side == "LONG"
            else primary.sweep_extreme + selected_config.stop_buffer_atr * session_atr
        )
        entry_reference = entry_bar.open if entry_bar is not None and entry_bar.complete else None
        risk_distance = abs(entry_reference - invalidation) if entry_reference is not None else None
        outcome_rows: tuple[PathOutcome, ...] = ()
        status = "TRIGGERED"
        no_trigger_reason = None
        if (
            entry_bar is None
            or not entry_bar.complete
            or risk_distance is None
            or risk_distance <= 0
        ):
            status = "OUTCOME_INCOMPLETE"
            no_trigger_reason = "NEXT_COMPLETE_ENTRY_BAR_UNAVAILABLE"
        else:
            entry_price = cast(float, entry_reference)
            outcome_rows = tuple(
                _calculate_path_outcome(
                    bars_by_open,
                    entry_time=entry_time,
                    entry_price=entry_price,
                    invalidation_price=invalidation,
                    side=primary.side,
                    horizon_minutes=horizon,
                    target_r_levels=selected_config.target_r_levels,
                )
                for horizon in selected_config.outcome_horizons_minutes
            )
            if any(outcome.status != "COMPLETE" for outcome in outcome_rows):
                status = "OUTCOME_INCOMPLETE"
                no_trigger_reason = "ONE_OR_MORE_OUTCOME_HORIZONS_INCOMPLETE"

        alignment = _bias_alignment(
            primary.side,
            fundamental,
            config=selected_config,
        )
        evidence = {
            **base_evidence,
            "primary_attempt_index": attempts.index(primary),
            "two_sided_trigger": len({attempt.side for attempt in triggered}) > 1,
            "displacement_bar": _five_minute_payload(displacement_bar),
            "reference_level_confluence": _level_confluence(
                primary,
                reference_levels,
                atr=session_atr,
            ),
        }
        opportunity_hash = _opportunity_hash(
            session_date=session_date,
            status=status,
            asia=asia,
            reference_levels=reference_levels,
            fundamental=fundamental,
            attempts=attempts,
            outcomes=outcome_rows,
            config=selected_config,
        )
        opportunities.append(
            SessionOpportunity(
                session_date=session_date,
                fundamental_freeze_time=clocks["fundamental_freeze"],
                level_freeze_time=clocks["london_start"],
                london_start_time=clocks["london_start"],
                london_end_time=clocks["london_end"],
                status=status,
                no_trigger_reason=no_trigger_reason,
                asia_range=asia,
                asia_range_percentile=range_percentile,
                asia_compression_state=compression_state,
                reference_levels=reference_levels,
                fundamental=fundamental,
                attempts=tuple(attempts),
                setup_side=primary.side,
                signal_time=primary.displacement_time,
                entry_time=entry_time,
                entry_reference_price=entry_reference,
                invalidation_price=invalidation,
                risk_distance=risk_distance,
                bias_alignment=alignment,
                outcomes=outcome_rows,
                data_hash=opportunity_hash,
                evidence=evidence,
            )
        )

    summary = summarize_session_opportunities(opportunities)
    price_hash = _price_data_hash(bars)
    return SessionEdgeStudyResult(
        strategy=SESSION_EDGE_RULESET_VERSION,
        opportunities=tuple(opportunities),
        summary=summary,
        provenance={
            "ruleset_version": SESSION_EDGE_RULESET_VERSION,
            "summary_version": SESSION_EDGE_SUMMARY_VERSION,
            "config": _jsonable(asdict(selected_config)),
            "source_1m_bars": len(bars),
            "aggregated_5m_bars": len(five_minute),
            "complete_5m_bars": sum(item.complete for item in five_minute),
            "price_data_hash_sha256": price_hash,
            "point_in_time_policy": (
                "Each five-minute bucket uses the earliest one-minute version and "
                "is complete only when all five records were available by bucket "
                "close. Fundamentals are frozen before London. Unknown catalyst "
                "risk is retained as a cohort and is never treated as known-safe."
            ),
            "session_definition": {
                "asia": (
                    f"{selected_config.asia_start_local}-"
                    f"{selected_config.asia_end_local} Asia/Tokyo"
                ),
                "fundamental_freeze_minutes_before_london": (
                    selected_config.fundamental_freeze_minutes_before
                ),
                "london": (
                    f"{selected_config.london_start_local}-"
                    f"{selected_config.london_end_local} Europe/London"
                ),
                "gold_trading_day_roll": "17:00 America/New_York",
            },
            "research_status": "RESEARCH / EDGE NOT YET ESTABLISHED",
        },
    )


def summarize_session_opportunities(
    opportunities: Sequence[SessionOpportunity],
) -> dict[str, Any]:
    status_counts: dict[str, int] = defaultdict(int)
    for opportunity in opportunities:
        status_counts[opportunity.status] += 1
    triggered = [item for item in opportunities if item.setup_side is not None]
    volume_expansion = [
        item
        for item in triggered
        if (
            (attempt := _primary_attempt(item)) is not None
            and attempt.tick_volume_percentile is not None
            and attempt.tick_volume_percentile >= 60
        )
    ]
    volume_not_expanded = [
        item
        for item in triggered
        if (
            (attempt := _primary_attempt(item)) is not None
            and attempt.tick_volume_percentile is not None
            and attempt.tick_volume_percentile < 60
        )
    ]
    normal_spread = [
        item
        for item in triggered
        if (
            (attempt := _primary_attempt(item)) is not None
            and attempt.spread_percentile is not None
            and attempt.spread_percentile <= 80
        )
    ]
    elevated_spread = [
        item
        for item in triggered
        if (
            (attempt := _primary_attempt(item)) is not None
            and attempt.spread_percentile is not None
            and attempt.spread_percentile > 80
        )
    ]
    level_confluence = [
        item
        for item in triggered
        if bool(item.evidence.get("reference_level_confluence"))
    ]
    quality_price_liquidity = [
        item
        for item in triggered
        if item.asia_compression_state == "COMPRESSED"
        and item in volume_expansion
        and item in normal_spread
    ]
    cohorts: dict[str, list[SessionOpportunity]] = {
        "ALL_TRIGGERED": triggered,
        "FUNDAMENTAL_ALIGNED": [item for item in triggered if item.bias_alignment == "ALIGNED"],
        "FUNDAMENTAL_OPPOSED": [item for item in triggered if item.bias_alignment == "OPPOSED"],
        "FUNDAMENTAL_NEUTRAL_OR_INSUFFICIENT": [
            item
            for item in triggered
            if item.bias_alignment in {"NEUTRAL", "INSUFFICIENT_FUNDAMENTALS", "UNKNOWN"}
        ],
        "CATALYST_KNOWN_LOW": [
            item for item in triggered if item.fundamental.get("event_risk") == "LOW"
        ],
        "CATALYST_UNKNOWN": [
            item for item in triggered if item.fundamental.get("event_risk") == "UNKNOWN"
        ],
        "CATALYST_ELEVATED_OR_HIGHER": [
            item
            for item in triggered
            if item.fundamental.get("event_risk") in {"ELEVATED", "HIGH", "EXTREME"}
        ],
        "COMPRESSED_ASIA": [
            item for item in triggered if item.asia_compression_state == "COMPRESSED"
        ],
        "NON_COMPRESSED_ASIA": [
            item for item in triggered if item.asia_compression_state == "NOT_COMPRESSED"
        ],
        "VOLUME_EXPANSION": volume_expansion,
        "VOLUME_NOT_EXPANDED": volume_not_expanded,
        "NORMAL_SPREAD": normal_spread,
        "ELEVATED_SPREAD": elevated_spread,
        "REFERENCE_LEVEL_CONFLUENCE": level_confluence,
        "NO_REFERENCE_LEVEL_CONFLUENCE": [
            item for item in triggered if item not in level_confluence
        ],
        "QUALITY_PRICE_LIQUIDITY": quality_price_liquidity,
        "FUNDAMENTAL_ALIGNED_QUALITY_PRICE_LIQUIDITY": [
            item
            for item in quality_price_liquidity
            if item.bias_alignment == "ALIGNED"
        ],
        "SAME_BAR_RECLAIM": [
            item
            for item in triggered
            if (
                (attempt := _primary_attempt(item)) is not None
                and attempt.reclaim_time == attempt.sweep_time
            )
        ],
        "DELAYED_RECLAIM": [
            item
            for item in triggered
            if (
                (attempt := _primary_attempt(item)) is not None
                and attempt.reclaim_time != attempt.sweep_time
            )
        ],
        "SHALLOW_SWEEP_0_TO_0_25_ATR": [
            item
            for item in triggered
            if (
                (attempt := _primary_attempt(item)) is not None
                and attempt.depth_atr <= 0.25
            )
        ],
        "DEEPER_SWEEP_0_25_TO_0_75_ATR": [
            item
            for item in triggered
            if (
                (attempt := _primary_attempt(item)) is not None
                and attempt.depth_atr > 0.25
            )
        ],
        "LONG": [item for item in triggered if item.setup_side == "LONG"],
        "SHORT": [item for item in triggered if item.setup_side == "SHORT"],
    }
    for value in sorted(
        {
            str(item.fundamental.get("regime_label") or "UNKNOWN")
            for item in triggered
        }
    ):
        cohorts[f"REGIME::{value}"] = [
            item
            for item in triggered
            if str(item.fundamental.get("regime_label") or "UNKNOWN") == value
        ]
    for value in sorted(
        {
            str(item.fundamental.get("dominant_driver") or "UNKNOWN")
            for item in triggered
        }
    ):
        cohorts[f"DRIVER::{value}"] = [
            item
            for item in triggered
            if str(item.fundamental.get("dominant_driver") or "UNKNOWN") == value
        ]
    return {
        "research_status": "RESEARCH / EDGE NOT YET ESTABLISHED",
        "session_count": len(opportunities),
        "complete_session_count": sum(
            item.status != "INCOMPLETE_SESSION" for item in opportunities
        ),
        "trigger_count": len(triggered),
        "trigger_rate_pct": _percentage(len(triggered), len(opportunities)),
        "status_funnel": dict(sorted(status_counts.items())),
        "cohorts": {
            name: _summarize_cohort(members, cohort=name) for name, members in cohorts.items()
        },
        "cohort_contract": (
            "Compression, 60th-percentile tick-volume expansion, 80th-percentile "
            "spread state, reference-level confluence, reclaim speed, sweep depth, "
            "regime, and dominant driver are descriptive matched cohorts. They are "
            "not optimized entry gates."
        ),
        "interpretation": (
            "These are observational path outcomes, not simulated trades. Positive "
            "MFE or gross path outcome does not establish an executable edge until "
            "entry, exit, transaction costs, catalyst rules, and locked validation "
            "are tested separately."
        ),
    }


def _primary_attempt(opportunity: SessionOpportunity) -> SweepAttempt | None:
    value = opportunity.evidence.get("primary_attempt_index")
    if not isinstance(value, int) or value < 0 or value >= len(opportunity.attempts):
        return None
    return opportunity.attempts[value]


def opportunity_to_dict(opportunity: SessionOpportunity) -> dict[str, Any]:
    return cast(dict[str, Any], _jsonable(asdict(opportunity)))


def _build_asia_ranges(
    bars: Sequence[SessionEdgeFiveMinuteBar],
    *,
    start_date: date,
    end_date: date,
    config: SessionEdgeConfig,
) -> dict[date, AsiaRange]:
    by_open = {bar.open_time: bar for bar in bars}
    output: dict[date, AsiaRange] = {}
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            clocks = london_session_clocks(current, config)
            expected = _expected_five_minute_opens(clocks["asia_start"], clocks["asia_end"])
            members = [
                by_open[open_time]
                for open_time in expected
                if open_time in by_open and by_open[open_time].complete
            ]
            complete = len(members) == len(expected)
            output[current] = AsiaRange(
                session_date=current,
                start_time=clocks["asia_start"],
                end_time=clocks["asia_end"],
                status="COMPLETE" if complete else "INCOMPLETE",
                bar_count=len(members),
                expected_bar_count=len(expected),
                open=members[0].open if members else None,
                high=max((item.high for item in members), default=None),
                low=min((item.low for item in members), default=None),
                close=members[-1].close if members else None,
                range_size=(
                    max(item.high for item in members) - min(item.low for item in members)
                    if members
                    else None
                ),
            )
        current += timedelta(days=1)
    return output


def _empty_asia_range(session_date: date, clocks: dict[str, datetime]) -> AsiaRange:
    return AsiaRange(
        session_date=session_date,
        start_time=clocks["asia_start"],
        end_time=clocks["asia_end"],
        status="INCOMPLETE",
        bar_count=0,
        expected_bar_count=int((clocks["asia_end"] - clocks["asia_start"]).total_seconds() // 300),
        open=None,
        high=None,
        low=None,
        close=None,
        range_size=None,
    )


def _requested_session_dates(
    start: datetime,
    end: datetime,
    config: SessionEdgeConfig,
) -> list[date]:
    current = start.astimezone(LONDON).date()
    final = end.astimezone(LONDON).date()
    output: list[date] = []
    while current <= final:
        if current.weekday() < 5:
            clocks = london_session_clocks(current, config)
            if clocks["fundamental_freeze"] >= start and clocks["london_end"] <= end:
                output.append(current)
        current += timedelta(days=1)
    return output


def _build_reference_level_index(
    bars: Sequence[SessionEdgeFiveMinuteBar],
) -> _ReferenceLevelIndex:
    by_trading_day: dict[date, list[SessionEdgeFiveMinuteBar]] = defaultdict(list)
    for bar in bars:
        if bar.complete:
            by_trading_day[_gold_trading_date(bar.open_time)].append(bar)
    day_summaries: dict[date, _LevelSummary] = {}
    week_members: dict[tuple[int, int], list[SessionEdgeFiveMinuteBar]] = defaultdict(list)
    for trading_date, members in by_trading_day.items():
        ordered = sorted(members, key=lambda item: item.open_time)
        day_summaries[trading_date] = _LevelSummary(
            open_time=ordered[0].open_time,
            open=ordered[0].open,
            high=max(item.high for item in ordered),
            low=min(item.low for item in ordered),
            close=ordered[-1].close,
        )
        week_members[trading_date.isocalendar()[:2]].extend(ordered)
    week_summaries: dict[tuple[int, int], _LevelSummary] = {}
    for week, members in week_members.items():
        ordered = sorted(members, key=lambda item: item.open_time)
        week_summaries[week] = _LevelSummary(
            open_time=ordered[0].open_time,
            open=ordered[0].open,
            high=max(item.high for item in ordered),
            low=min(item.low for item in ordered),
            close=ordered[-1].close,
        )
    return _ReferenceLevelIndex(
        trading_dates=tuple(sorted(day_summaries)),
        trading_days=day_summaries,
        trading_weeks=week_summaries,
    )


def _reference_levels(
    index: _ReferenceLevelIndex,
    *,
    freeze_time: datetime,
) -> dict[str, float | None]:
    if not index.trading_dates:
        return {
            "TRADING_DAY_OPEN": None,
            "PREVIOUS_DAY_HIGH": None,
            "PREVIOUS_DAY_LOW": None,
            "PREVIOUS_DAY_CLOSE": None,
            "PREVIOUS_WEEK_HIGH": None,
            "PREVIOUS_WEEK_LOW": None,
        }
    current_day = _gold_trading_date(freeze_time)
    current_summary = index.trading_days.get(current_day)
    previous_index = bisect_left(index.trading_dates, current_day) - 1
    previous_summary = (
        index.trading_days[index.trading_dates[previous_index]]
        if previous_index >= 0
        else None
    )
    current_week = current_day.isocalendar()[:2]
    prior_weeks = sorted(value for value in index.trading_weeks if value < current_week)
    previous_week = index.trading_weeks[prior_weeks[-1]] if prior_weeks else None
    return {
        "TRADING_DAY_OPEN": (
            current_summary.open
            if current_summary is not None and current_summary.open_time <= freeze_time
            else None
        ),
        "PREVIOUS_DAY_HIGH": previous_summary.high if previous_summary is not None else None,
        "PREVIOUS_DAY_LOW": previous_summary.low if previous_summary is not None else None,
        "PREVIOUS_DAY_CLOSE": previous_summary.close if previous_summary is not None else None,
        "PREVIOUS_WEEK_HIGH": previous_week.high if previous_week is not None else None,
        "PREVIOUS_WEEK_LOW": previous_week.low if previous_week is not None else None,
    }


def _gold_trading_date(timestamp: datetime) -> date:
    local = timestamp.astimezone(NEW_YORK)
    return local.date() + timedelta(days=1) if local.time() >= time(17, 0) else local.date()


def _build_atr_index(
    bars: Sequence[SessionEdgeFiveMinuteBar],
    *,
    window: int,
) -> _AtrIndex:
    true_ranges: list[float] = []
    prior_close: float | None = None
    close_times: list[datetime] = []
    values: list[float] = []
    for bar in bars:
        if not bar.complete:
            continue
        value = bar.high - bar.low
        if prior_close is not None:
            value = max(value, abs(bar.high - prior_close), abs(bar.low - prior_close))
        true_ranges.append(value)
        prior_close = bar.close
        if len(true_ranges) >= window:
            close_times.append(bar.close_time)
            values.append(statistics.mean(true_ranges[-window:]))
    return _AtrIndex(close_times=tuple(close_times), values=tuple(values))


def _atr_before(index: _AtrIndex, *, before: datetime) -> float | None:
    position = bisect_right(index.close_times, before) - 1
    return index.values[position] if position >= 0 else None


def _detect_sweep_attempts(
    all_bars: Sequence[SessionEdgeFiveMinuteBar],
    *,
    global_indices: dict[datetime, int],
    london_bars: Sequence[SessionEdgeFiveMinuteBar],
    asia: AsiaRange,
    atr: float,
    config: SessionEdgeConfig,
) -> list[SweepAttempt]:
    if asia.low is None or asia.high is None:
        return []
    attempts: list[SweepAttempt] = []
    levels: tuple[tuple[Side, str, float], ...] = (
        ("LONG", "ASIA_LOW", asia.low),
        ("SHORT", "ASIA_HIGH", asia.high),
    )
    for local_index, bar in enumerate(london_bars):
        previous = london_bars[local_index - 1] if local_index else None
        for side, level_code, level in levels:
            crossed = (
                bar.low < level and (previous is None or previous.close >= level)
                if side == "LONG"
                else bar.high > level and (previous is None or previous.close <= level)
            )
            if not crossed:
                continue
            attempts.append(
                _evaluate_attempt(
                    all_bars,
                    global_indices=global_indices,
                    london_bars=london_bars,
                    sweep_index=local_index,
                    side=side,
                    level_code=level_code,
                    level=level,
                    atr=atr,
                    config=config,
                )
            )
    return attempts


def _evaluate_attempt(
    all_bars: Sequence[SessionEdgeFiveMinuteBar],
    *,
    global_indices: dict[datetime, int],
    london_bars: Sequence[SessionEdgeFiveMinuteBar],
    sweep_index: int,
    side: Side,
    level_code: str,
    level: float,
    atr: float,
    config: SessionEdgeConfig,
) -> SweepAttempt:
    sweep_bar = london_bars[sweep_index]
    reclaim_members = london_bars[sweep_index : sweep_index + config.reclaim_bars]
    reclaim_index: int | None = None
    for offset, candidate in enumerate(reclaim_members):
        reclaimed = candidate.close > level if side == "LONG" else candidate.close < level
        if reclaimed:
            reclaim_index = sweep_index + offset
            break
    excursion_members = (
        london_bars[sweep_index : reclaim_index + 1]
        if reclaim_index is not None
        else reclaim_members
    )
    extreme = (
        min(item.low for item in excursion_members)
        if side == "LONG"
        else max(item.high for item in excursion_members)
    )
    depth = level - extreme if side == "LONG" else extreme - level
    depth_atr = depth / atr
    qualified = config.sweep_min_atr <= depth_atr <= config.sweep_max_atr
    reason = (
        "QUALIFIED"
        if qualified
        else "SWEEP_TOO_SHALLOW"
        if depth_atr < config.sweep_min_atr
        else "SWEEP_TOO_DEEP"
    )
    global_index = global_indices[sweep_bar.open_time]
    prior_bars = [
        item
        for item in all_bars[
            max(0, global_index - config.micro_structure_lookback_bars) : global_index
        ]
        if item.complete
    ]
    micro_level = (
        (
            max(item.high for item in prior_bars)
            if side == "LONG"
            else min(item.low for item in prior_bars)
        )
        if len(prior_bars) == config.micro_structure_lookback_bars
        else None
    )
    displacement: SessionEdgeFiveMinuteBar | None = None
    volume_percentile: float | None = None
    spread_percentile: float | None = None
    body_atr: float | None = None
    body_ratio: float | None = None
    close_location: float | None = None
    if qualified and reclaim_index is not None and micro_level is not None:
        displacement_members = london_bars[
            reclaim_index : reclaim_index + config.displacement_bars_after_reclaim
        ]
        for candidate in displacement_members:
            qualifies, metrics = _is_displacement(
                candidate,
                side=side,
                micro_level=micro_level,
                atr=atr,
                config=config,
            )
            if not qualifies:
                continue
            candidate_global_index = global_indices[candidate.open_time]
            prior_liquidity = [
                item
                for item in all_bars[
                    max(
                        0, candidate_global_index - config.liquidity_lookback_bars
                    ) : candidate_global_index
                ]
                if item.complete
            ]
            volume_percentile = _percentile_rank(
                candidate.tick_volume,
                [item.tick_volume for item in prior_liquidity if item.tick_volume is not None],
            )
            spread_percentile = _percentile_rank(
                candidate.spread_price,
                [item.spread_price for item in prior_liquidity if item.spread_price is not None],
            )
            displacement = candidate
            body_atr = metrics["body_atr"]
            body_ratio = metrics["body_ratio"]
            close_location = metrics["close_location"]
            break

    if displacement is not None:
        path_to_trigger = [
            item for item in london_bars[sweep_index:] if item.open_time <= displacement.open_time
        ]
        trigger_extreme = (
            min(item.low for item in path_to_trigger)
            if side == "LONG"
            else max(item.high for item in path_to_trigger)
        )
        trigger_depth = level - trigger_extreme if side == "LONG" else trigger_extreme - level
        trigger_depth_atr = trigger_depth / atr
        if trigger_depth_atr > config.sweep_max_atr:
            qualified = False
            reason = "SWEEP_TOO_DEEP_BEFORE_TRIGGER"
            displacement = None
        else:
            extreme = trigger_extreme
            depth = trigger_depth
            depth_atr = trigger_depth_atr

    return SweepAttempt(
        side=side,
        level_code=level_code,
        level=level,
        sweep_time=sweep_bar.close_time,
        sweep_extreme=extreme,
        depth_price=depth,
        depth_atr=depth_atr,
        qualified=qualified,
        qualification_reason=reason,
        reclaim_time=(london_bars[reclaim_index].close_time if reclaim_index is not None else None),
        micro_structure_level=micro_level,
        displacement_time=displacement.close_time if displacement is not None else None,
        displacement_body_atr=body_atr if displacement is not None else None,
        displacement_body_ratio=body_ratio if displacement is not None else None,
        displacement_close_location=close_location if displacement is not None else None,
        tick_volume_percentile=volume_percentile if displacement is not None else None,
        spread_percentile=spread_percentile if displacement is not None else None,
        triggered=qualified and displacement is not None,
    )


def _is_displacement(
    bar: SessionEdgeFiveMinuteBar,
    *,
    side: Side,
    micro_level: float,
    atr: float,
    config: SessionEdgeConfig,
) -> tuple[bool, dict[str, float]]:
    bar_range = bar.high - bar.low
    body = abs(bar.close - bar.open)
    body_atr = body / atr
    body_ratio = body / bar_range if bar_range > 0 else 0.0
    close_location = (
        (bar.close - bar.low) / bar_range
        if side == "LONG" and bar_range > 0
        else (bar.high - bar.close) / bar_range
        if bar_range > 0
        else 0.0
    )
    directional = bar.close > bar.open if side == "LONG" else bar.close < bar.open
    structure_break = bar.close > micro_level if side == "LONG" else bar.close < micro_level
    qualifies = (
        directional
        and structure_break
        and body_atr >= config.displacement_min_body_atr
        and body_ratio >= config.displacement_min_body_ratio
        and close_location >= config.displacement_min_close_location
    )
    return qualifies, {
        "body_atr": body_atr,
        "body_ratio": body_ratio,
        "close_location": close_location,
    }


def _calculate_path_outcome(
    bars_by_open: dict[datetime, SessionEdgeFiveMinuteBar],
    *,
    entry_time: datetime,
    entry_price: float,
    invalidation_price: float,
    side: Side,
    horizon_minutes: int,
    target_r_levels: Sequence[float],
) -> PathOutcome:
    expected_opens = [
        entry_time + timedelta(minutes=offset) for offset in range(0, horizon_minutes, 5)
    ]
    members = [
        bars_by_open[open_time]
        for open_time in expected_opens
        if open_time in bars_by_open and bars_by_open[open_time].complete
    ]
    complete = len(members) == len(expected_opens)
    risk = abs(entry_price - invalidation_price)
    if not members or risk <= 0:
        return PathOutcome(
            horizon_minutes=horizon_minutes,
            status="INCOMPLETE",
            bar_count=len(members),
            expected_bar_count=len(expected_opens),
            terminal_price=None,
            terminal_return_pct=None,
            terminal_r=None,
            mfe_price=None,
            mae_price=None,
            mfe_r=None,
            mae_r=None,
            target_before_stop={_r_key(level): None for level in target_r_levels},
            gross_path_outcome_r_1r=None,
        )
    direction = 1.0 if side == "LONG" else -1.0
    favourable = (
        max(item.high for item in members) - entry_price
        if side == "LONG"
        else entry_price - min(item.low for item in members)
    )
    adverse = (
        entry_price - min(item.low for item in members)
        if side == "LONG"
        else max(item.high for item in members) - entry_price
    )
    terminal = members[-1].close
    terminal_r = direction * (terminal - entry_price) / risk
    target_results = {
        _r_key(level): _target_before_stop(
            members,
            side=side,
            entry_price=entry_price,
            risk=risk,
            target_r=level,
        )
        for level in target_r_levels
    }
    one_r_result = _target_before_stop(
        members,
        side=side,
        entry_price=entry_price,
        risk=risk,
        target_r=1.0,
    )
    gross_path_outcome = (
        1.0
        if one_r_result is True
        else -1.0
        if one_r_result is False
        else max(-1.0, min(1.0, terminal_r))
    )
    return PathOutcome(
        horizon_minutes=horizon_minutes,
        status="COMPLETE" if complete else "INCOMPLETE",
        bar_count=len(members),
        expected_bar_count=len(expected_opens),
        terminal_price=terminal,
        terminal_return_pct=direction * (terminal - entry_price) / entry_price * 100,
        terminal_r=terminal_r,
        mfe_price=max(0.0, favourable),
        mae_price=max(0.0, adverse),
        mfe_r=max(0.0, favourable / risk),
        mae_r=max(0.0, adverse / risk),
        target_before_stop=target_results,
        gross_path_outcome_r_1r=gross_path_outcome,
    )


def _target_before_stop(
    bars: Sequence[SessionEdgeFiveMinuteBar],
    *,
    side: Side,
    entry_price: float,
    risk: float,
    target_r: float,
) -> bool | None:
    stop = entry_price - risk if side == "LONG" else entry_price + risk
    target = entry_price + target_r * risk if side == "LONG" else entry_price - target_r * risk
    for bar in bars:
        stop_touched = bar.low <= stop if side == "LONG" else bar.high >= stop
        target_touched = bar.high >= target if side == "LONG" else bar.low <= target
        if stop_touched:
            return False
        if target_touched:
            return True
    return None


def _fundamental_payload(
    state: FundamentalState | None,
    *,
    freeze_time: datetime,
) -> dict[str, Any]:
    if state is None:
        return {
            "as_of": freeze_time.isoformat(),
            "directional_score": None,
            "confidence": None,
            "coverage": None,
            "bias_label": "UNKNOWN",
            "regime_label": "UNKNOWN",
            "reaction_function": "UNKNOWN",
            "dominant_driver": None,
            "main_contradiction": None,
            "event_risk": "UNKNOWN",
            "upcoming_catalyst": None,
            "components": [],
            "data_hash": None,
            "epistemic_status": "UNKNOWN",
        }
    if state.as_of.astimezone(UTC) != freeze_time.astimezone(UTC):
        raise ValueError("Fundamental evaluator must return the exact requested freeze clock")
    return {
        "as_of": state.as_of.isoformat(),
        "directional_score": state.directional_score,
        "confidence": state.confidence,
        "coverage": state.coverage,
        "bias_label": state.bias_label,
        "regime_label": state.regime_label,
        "reaction_function": state.reaction_function,
        "dominant_driver": state.dominant_driver,
        "main_contradiction": state.main_contradiction,
        "event_risk": state.event_risk,
        "upcoming_catalyst": state.upcoming_catalyst,
        "components": [
            {
                "code": component.code,
                "layer": component.layer,
                "direction": component.direction,
                "contribution": component.contribution,
                "confidence": component.confidence,
                "epistemic_status": component.epistemic_status,
                "evidence": component.evidence,
            }
            for component in state.components
        ],
        "data_hash": state.data_hash,
        "epistemic_status": "INFERRED",
    }


def _bias_alignment(
    side: Side,
    fundamental: dict[str, Any],
    *,
    config: SessionEdgeConfig,
) -> BiasAlignment:
    score = fundamental.get("directional_score")
    coverage = fundamental.get("coverage")
    confidence = fundamental.get("confidence")
    if score is None or coverage is None or confidence is None:
        return "UNKNOWN"
    if (
        float(coverage) < config.fundamental_min_coverage
        or float(confidence) < config.fundamental_min_confidence
    ):
        return "INSUFFICIENT_FUNDAMENTALS"
    numeric_score = float(score)
    if abs(numeric_score) < config.fundamental_min_score:
        return "NEUTRAL"
    fundamental_side = "LONG" if numeric_score > 0 else "SHORT"
    return "ALIGNED" if side == fundamental_side else "OPPOSED"


def _opportunity_without_trigger(
    *,
    session_date: date,
    clocks: dict[str, datetime],
    status: str,
    reason: str,
    asia: AsiaRange,
    range_percentile: float | None,
    compression_state: str,
    reference_levels: dict[str, float | None],
    fundamental: dict[str, Any],
    evidence: dict[str, Any],
    config: SessionEdgeConfig,
    attempts: Sequence[SweepAttempt] = (),
) -> SessionOpportunity:
    opportunity_hash = _opportunity_hash(
        session_date=session_date,
        status=status,
        asia=asia,
        reference_levels=reference_levels,
        fundamental=fundamental,
        attempts=attempts,
        outcomes=(),
        config=config,
    )
    return SessionOpportunity(
        session_date=session_date,
        fundamental_freeze_time=clocks["fundamental_freeze"],
        level_freeze_time=clocks["london_start"],
        london_start_time=clocks["london_start"],
        london_end_time=clocks["london_end"],
        status=status,
        no_trigger_reason=reason,
        asia_range=asia,
        asia_range_percentile=range_percentile,
        asia_compression_state=compression_state,
        reference_levels=reference_levels,
        fundamental=fundamental,
        attempts=tuple(attempts),
        setup_side=None,
        signal_time=None,
        entry_time=None,
        entry_reference_price=None,
        invalidation_price=None,
        risk_distance=None,
        bias_alignment="NOT_APPLICABLE",
        outcomes=(),
        data_hash=opportunity_hash,
        evidence=evidence,
    )


def _attempt_status(attempts: Sequence[SweepAttempt]) -> str:
    if not attempts:
        return "NO_SWEEP"
    if any(item.qualified and item.reclaim_time is not None for item in attempts):
        return "RECLAIMED_NO_DISPLACEMENT"
    if any(item.qualified for item in attempts):
        return "SWEEP_NOT_RECLAIMED"
    return "NO_QUALIFIED_SWEEP"


def _summarize_cohort(
    opportunities: Sequence[SessionOpportunity],
    *,
    cohort: str,
) -> dict[str, Any]:
    complete_outcomes: list[PathOutcome] = []
    for opportunity in opportunities:
        completed = [item for item in opportunity.outcomes if item.status == "COMPLETE"]
        if completed:
            complete_outcomes.append(max(completed, key=lambda item: item.horizon_minutes))
    gross_r = [
        item.gross_path_outcome_r_1r
        for item in complete_outcomes
        if item.gross_path_outcome_r_1r is not None
    ]
    mfe_r = [item.mfe_r for item in complete_outcomes if item.mfe_r is not None]
    mae_r = [item.mae_r for item in complete_outcomes if item.mae_r is not None]
    target_keys = sorted({key for item in complete_outcomes for key in item.target_before_stop})
    return {
        "setup_count": len(opportunities),
        "complete_outcome_count": len(complete_outcomes),
        "mean_gross_path_outcome_r_1r": _mean(gross_r),
        "median_gross_path_outcome_r_1r": _median(gross_r),
        "gross_path_outcome_r_bootstrap_95ci": _bootstrap_interval(
            gross_r,
            namespace=cohort,
        ),
        "mean_mfe_r": _mean(mfe_r),
        "median_mfe_r": _median(mfe_r),
        "mean_mae_r": _mean(mae_r),
        "median_mae_r": _median(mae_r),
        "target_before_stop_pct": {
            key: _percentage(
                sum(item.target_before_stop.get(key) is True for item in complete_outcomes),
                sum(item.target_before_stop.get(key) is not None for item in complete_outcomes),
            )
            for key in target_keys
        },
    }


def _level_confluence(
    attempt: SweepAttempt,
    reference_levels: dict[str, float | None],
    *,
    atr: float,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for code, level in reference_levels.items():
        if level is None or code == attempt.level_code:
            continue
        distance_atr = abs(level - attempt.level) / atr
        if distance_atr <= 0.25:
            output.append(
                {
                    "level_code": code,
                    "level": level,
                    "distance_atr": round(distance_atr, 6),
                }
            )
    return output


def _five_minute_payload(bar: SessionEdgeFiveMinuteBar) -> dict[str, Any]:
    return {
        **asdict(bar),
        "open_time": bar.open_time.isoformat(),
        "close_time": bar.close_time.isoformat(),
        "available_at": bar.available_at.isoformat(),
    }


def _expected_five_minute_opens(start: datetime, end: datetime) -> list[datetime]:
    count = int((end - start).total_seconds() // 300)
    return [start + timedelta(minutes=5 * index) for index in range(count)]


def _parse_clock(value: str, field_name: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use HH:MM format") from exc
    if parsed.second or parsed.microsecond:
        raise ValueError(f"{field_name} must align to a whole minute")
    return parsed


def _validate_inputs(
    bars: Sequence[SessionEdgeBar],
    *,
    start: datetime,
    end: datetime,
    config: SessionEdgeConfig,
) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must include a timezone")
    if start >= end:
        raise ValueError("start must precede end")
    if not bars:
        raise ValueError("At least one price bar is required")
    if any(
        item.open_time.tzinfo is None
        or item.close_time.tzinfo is None
        or item.available_at.tzinfo is None
        for item in bars
    ):
        raise ValueError("All price-bar timestamps must include a timezone")
    if config.atr_lookback_bars < 2:
        raise ValueError("atr_lookback_bars must be at least 2")
    if config.compression_lookback_sessions < config.compression_min_history:
        raise ValueError("compression_lookback_sessions must be >= compression_min_history")
    if not 0 <= config.sweep_min_atr < config.sweep_max_atr:
        raise ValueError("Sweep ATR bounds are invalid")
    if config.reclaim_bars < 1 or config.displacement_bars_after_reclaim < 1:
        raise ValueError("Reclaim and displacement windows must be positive")
    if not config.outcome_horizons_minutes:
        raise ValueError("At least one outcome horizon is required")
    if any(value <= 0 or value % 5 for value in config.outcome_horizons_minutes):
        raise ValueError("Outcome horizons must be positive multiples of five")
    if any(value <= 0 for value in config.target_r_levels):
        raise ValueError("Target R levels must be positive")
    for field_name in (
        "asia_start_local",
        "asia_end_local",
        "london_start_local",
        "london_end_local",
    ):
        _parse_clock(str(getattr(config, field_name)), field_name)
    asia_duration = datetime.combine(
        date.min, _parse_clock(config.asia_end_local, "asia_end_local")
    ) - datetime.combine(
        date.min,
        _parse_clock(config.asia_start_local, "asia_start_local"),
    )
    london_duration = datetime.combine(
        date.min,
        _parse_clock(config.london_end_local, "london_end_local"),
    ) - datetime.combine(
        date.min,
        _parse_clock(config.london_start_local, "london_start_local"),
    )
    if asia_duration <= timedelta() or london_duration <= timedelta():
        raise ValueError("Session end clocks must be after their start clocks")
    if asia_duration.total_seconds() % 300 or london_duration.total_seconds() % 300:
        raise ValueError("Session windows must contain whole five-minute buckets")


def _opportunity_hash(
    *,
    session_date: date,
    status: str,
    asia: AsiaRange,
    reference_levels: dict[str, float | None],
    fundamental: dict[str, Any],
    attempts: Sequence[SweepAttempt],
    outcomes: Sequence[PathOutcome],
    config: SessionEdgeConfig,
) -> str:
    payload = {
        "session_date": session_date.isoformat(),
        "status": status,
        "asia": _jsonable(asdict(asia)),
        "reference_levels": reference_levels,
        "fundamental_data_hash": fundamental.get("data_hash"),
        "attempts": _jsonable([asdict(item) for item in attempts]),
        "outcomes": _jsonable([asdict(item) for item in outcomes]),
        "config": _jsonable(asdict(config)),
        "ruleset_version": SESSION_EDGE_RULESET_VERSION,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _price_data_hash(bars: Sequence[SessionEdgeBar]) -> str:
    digest = hashlib.sha256()
    for bar in sorted(bars, key=lambda item: (item.open_time, item.available_at)):
        digest.update(
            (
                f"{bar.open_time.isoformat()}|{bar.close_time.isoformat()}|"
                f"{bar.open}|{bar.high}|{bar.low}|{bar.close}|"
                f"{bar.tick_volume}|{bar.spread_price}|{bar.available_at.isoformat()}"
            ).encode()
        )
    return digest.hexdigest()


def _percentile_rank(
    value: float | None,
    population: Sequence[float | None],
) -> float | None:
    if value is None:
        return None
    eligible = [float(item) for item in population if item is not None]
    if not eligible:
        return None
    return round(sum(item <= value for item in eligible) / len(eligible) * 100, 6)


def _bootstrap_interval(
    values: Sequence[float],
    *,
    namespace: str,
    iterations: int = 2_000,
) -> list[float | None]:
    if len(values) < 5:
        return [None, None]
    seed = int.from_bytes(
        hashlib.sha256(
            f"{namespace}|{','.join(f'{value:.10f}' for value in values)}".encode()
        ).digest()[:8],
        "big",
    )
    generator = random.Random(seed)
    means = sorted(
        statistics.mean(generator.choice(values) for _ in values) for _ in range(iterations)
    )
    return [
        round(means[int(0.025 * (len(means) - 1))], 6),
        round(means[int(0.975 * (len(means) - 1))], 6),
    ]


def _r_key(value: float) -> str:
    return f"{value:.2f}R"


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.mean(values), 6) if values else None


def _median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 6) if values else None


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value
