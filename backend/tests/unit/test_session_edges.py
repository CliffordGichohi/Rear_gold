from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from gold_intel.analytics.fundamentals import FundamentalState
from gold_intel.analytics.session_edges import (
    SessionEdgeBar,
    SessionEdgeConfig,
    SessionEdgeFiveMinuteBar,
    _calculate_path_outcome,
    build_london_session_opportunities,
    london_session_clocks,
    summarize_session_opportunities,
)
from gold_intel.application.session_edges import (
    _domain_opportunity,
    _opportunity_model,
)


def _fundamental_state(
    as_of: datetime,
    score: float = 25.0,
    event_risk: str = "LOW",
) -> FundamentalState:
    return FundamentalState(
        as_of=as_of,
        directional_score=score,
        confidence=70,
        coverage=65,
        bias_label="MODERATELY_BULLISH" if score > 0 else "MODERATELY_BEARISH",
        regime_label="TEST_REGIME",
        reaction_function="REAL_YIELD_FOCUSED",
        dominant_driver="REAL_YIELD",
        main_contradiction=None,
        event_risk=event_risk,
        upcoming_catalyst=(
            {
                "event_code": "US_CPI",
                "scheduled_at": (as_of + timedelta(days=2)).isoformat(),
                "importance": 5,
            }
            if event_risk != "UNKNOWN"
            else None
        ),
        components=(),
        layers=(),
        reasoning={"score_is_not_a_trade_signal": True},
        data_hash=f"fundamental:{as_of.isoformat()}:{score}",
    )


def _designed_long_sweep(
    *,
    missing_asia_minute: bool = False,
) -> list[SessionEdgeBar]:
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 7, 0, 0, tzinfo=UTC)
    output: list[SessionEdgeBar] = []
    value = 2400.0
    timestamp = start
    while timestamp < end:
        if missing_asia_minute and timestamp == datetime(2026, 1, 6, 1, 17, tzinfo=UTC):
            timestamp += timedelta(minutes=1)
            continue
        open_price = value
        close_price = value
        high = value + 0.5
        low = value - 0.5
        volume = 10.0

        if (
            datetime(2026, 1, 6, 8, 0, tzinfo=UTC)
            <= timestamp
            < datetime(2026, 1, 6, 8, 5, tzinfo=UTC)
        ):
            open_price = 2400.0
            close_price = 2400.1
            high = 2400.3
            low = 2399.0 if timestamp.minute == 0 else 2399.8
            value = close_price
        elif (
            datetime(2026, 1, 6, 8, 5, tzinfo=UTC)
            <= timestamp
            < datetime(2026, 1, 6, 8, 10, tzinfo=UTC)
        ):
            offset = timestamp.minute - 5
            open_price = 2400.1 + 0.24 * offset
            close_price = 2400.1 + 0.24 * (offset + 1)
            high = close_price + 0.1
            low = open_price - 0.1
            volume = 100.0
            value = close_price
        elif (
            datetime(2026, 1, 6, 8, 10, tzinfo=UTC)
            <= timestamp
            < datetime(2026, 1, 6, 8, 40, tzinfo=UTC)
        ):
            offset = int((timestamp - datetime(2026, 1, 6, 8, 10, tzinfo=UTC)).seconds / 60)
            open_price = 2401.3 + 0.12 * offset
            close_price = open_price + 0.12
            high = close_price + 0.1
            low = open_price - 0.1
            volume = 35.0
            value = close_price
        elif timestamp >= datetime(2026, 1, 6, 8, 40, tzinfo=UTC):
            open_price = value
            close_price = value
            high = value + 0.2
            low = value - 0.2

        close_time = timestamp + timedelta(minutes=1)
        output.append(
            SessionEdgeBar(
                open_time=timestamp,
                close_time=close_time,
                open=open_price,
                high=max(high, open_price, close_price),
                low=min(low, open_price, close_price),
                close=close_price,
                tick_volume=volume,
                available_at=close_time,
                spread_price=0.25,
                source_record_key=timestamp.isoformat(),
            )
        )
        timestamp = close_time
    return output


def test_london_sweep_reclaim_displacement_is_recorded_without_forcing_trade() -> None:
    start = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 7, 0, 0, tzinfo=UTC)
    result = build_london_session_opportunities(
        _designed_long_sweep(),
        start=start,
        end=end,
        fundamental_state_at=lambda as_of: _fundamental_state(as_of),
    )

    assert len(result.opportunities) == 1
    opportunity = result.opportunities[0]
    assert opportunity.status == "TRIGGERED"
    assert opportunity.setup_side == "LONG"
    assert opportunity.bias_alignment == "ALIGNED"
    assert opportunity.fundamental_freeze_time == datetime(2026, 1, 6, 7, 55, tzinfo=UTC)
    assert opportunity.signal_time == datetime(2026, 1, 6, 8, 10, tzinfo=UTC)
    assert opportunity.entry_time == opportunity.signal_time
    assert opportunity.attempts[0].qualification_reason == "QUALIFIED"
    assert opportunity.attempts[0].triggered is True
    assert opportunity.outcomes[-1].target_before_stop["0.50R"] is True
    assert result.summary["trigger_count"] == 1
    assert result.summary["cohorts"]["FUNDAMENTAL_ALIGNED"]["setup_count"] == 1
    assert result.summary["research_status"] == "RESEARCH / EDGE NOT YET ESTABLISHED"


def test_missing_asia_minute_is_an_explicit_incomplete_session() -> None:
    result = build_london_session_opportunities(
        _designed_long_sweep(missing_asia_minute=True),
        start=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        end=datetime(2026, 1, 7, 0, 0, tzinfo=UTC),
    )

    opportunity = result.opportunities[0]
    assert opportunity.status == "INCOMPLETE_SESSION"
    assert opportunity.no_trigger_reason == "ASIA_RANGE_INCOMPLETE"
    assert opportunity.setup_side is None


def test_unknown_catalyst_is_retained_as_a_cohort_not_erased() -> None:
    result = build_london_session_opportunities(
        _designed_long_sweep(),
        start=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        end=datetime(2026, 1, 7, 0, 0, tzinfo=UTC),
        fundamental_state_at=lambda as_of: _fundamental_state(
            as_of,
            event_risk="UNKNOWN",
        ),
    )

    assert result.opportunities[0].setup_side == "LONG"
    assert result.opportunities[0].fundamental["event_risk"] == "UNKNOWN"
    assert result.summary["cohorts"]["CATALYST_UNKNOWN"]["setup_count"] == 1


def test_later_price_revision_cannot_change_the_historical_trigger() -> None:
    bars = _designed_long_sweep()
    original = next(
        item for item in bars if item.open_time == datetime(2026, 1, 6, 1, 10, tzinfo=UTC)
    )
    bars.append(
        SessionEdgeBar(
            open_time=original.open_time,
            close_time=original.close_time,
            open=9999,
            high=9999,
            low=9999,
            close=9999,
            tick_volume=9999,
            available_at=datetime(2026, 1, 6, 23, 0, tzinfo=UTC),
            spread_price=99,
            source_record_key="later-revision",
        )
    )
    result = build_london_session_opportunities(
        bars,
        start=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        end=datetime(2026, 1, 7, 0, 0, tzinfo=UTC),
    )

    opportunity = result.opportunities[0]
    assert opportunity.asia_range.high is not None
    assert opportunity.asia_range.high < 3000
    assert opportunity.setup_side == "LONG"


def test_london_clocks_follow_dst_without_manual_offsets() -> None:
    winter = london_session_clocks(date(2026, 1, 6), SessionEdgeConfig())
    summer = london_session_clocks(date(2026, 7, 6), SessionEdgeConfig())

    assert winter["london_start"] == datetime(2026, 1, 6, 8, 0, tzinfo=UTC)
    assert summer["london_start"] == datetime(2026, 7, 6, 7, 0, tzinfo=UTC)
    assert winter["fundamental_freeze"].minute == 55
    assert summer["fundamental_freeze"].minute == 55


def test_intrabar_target_and_stop_collision_is_scored_stop_first() -> None:
    entry_time = datetime(2026, 1, 6, 8, 0, tzinfo=UTC)
    bar = SessionEdgeFiveMinuteBar(
        open_time=entry_time,
        close_time=entry_time + timedelta(minutes=5),
        open=100,
        high=102,
        low=98,
        close=101,
        tick_volume=10,
        spread_price=0.1,
        available_at=entry_time + timedelta(minutes=5),
        complete=True,
    )
    outcome = _calculate_path_outcome(
        {entry_time: bar},
        entry_time=entry_time,
        entry_price=100,
        invalidation_price=99,
        side="LONG",
        horizon_minutes=5,
        target_r_levels=(1.0,),
    )

    assert outcome.target_before_stop["1.00R"] is False
    assert outcome.gross_path_outcome_r_1r == -1


def test_persisted_opportunity_round_trip_preserves_cohort_evidence() -> None:
    result = build_london_session_opportunities(
        _designed_long_sweep(),
        start=datetime(2026, 1, 6, 0, 0, tzinfo=UTC),
        end=datetime(2026, 1, 7, 0, 0, tzinfo=UTC),
        fundamental_state_at=lambda as_of: _fundamental_state(as_of),
    )
    original = result.opportunities[0]
    model = _opportunity_model(uuid4(), original)
    reconstructed = _domain_opportunity(model)

    assert reconstructed.data_hash == original.data_hash
    assert reconstructed.attempts == original.attempts
    assert reconstructed.outcomes == original.outcomes
    assert summarize_session_opportunities([reconstructed])["cohorts"][
        "FUNDAMENTAL_ALIGNED"
    ]["setup_count"] == 1
