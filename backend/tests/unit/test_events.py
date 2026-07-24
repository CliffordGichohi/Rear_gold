from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from gold_intel.analytics.event_studies import (
    ReactionBar,
    calculate_event_reactions,
)
from gold_intel.analytics.events import (
    EventReleaseFact,
    ForecastFact,
    calculate_economic_surprises,
)
from gold_intel.api.schemas import EconomicEventBundleRequest


def _release(
    *,
    released_at: datetime,
    actual: float = 0.2,
    component: str = "CPI_CORE_MOM",
    is_revision: bool = False,
) -> EventReleaseFact:
    return EventReleaseFact(
        event_id=uuid4(),
        release_id=uuid4(),
        event_code="US_CPI",
        event_name="US Consumer Price Index",
        scheduled_at=released_at,
        importance=5,
        component_code=component,
        observation_period=date(2026, 5, 1),
        actual_value=actual,
        previous_value=0.3,
        revised_previous_value=None,
        unit="PERCENT",
        released_at=released_at,
        available_at=released_at + timedelta(seconds=2),
        is_revision=is_revision,
        vintage="2026-06-10-original",
        is_synthetic=False,
    )


def _forecast(
    release: EventReleaseFact,
    *,
    value: float = 0.3,
    available_at: datetime | None = None,
) -> ForecastFact:
    availability = available_at or release.released_at - timedelta(hours=1)
    return ForecastFact(
        forecast_id=uuid4(),
        event_code=release.event_code,
        scheduled_at=release.scheduled_at,
        component_code=release.component_code,
        forecast_value=value,
        unit=release.unit,
        forecast_as_of=availability,
        available_at=availability,
        provider_code="MANUAL_CONSENSUS",
        vintage="pre-release",
        is_synthetic=False,
    )


def test_post_release_forecast_is_structurally_ineligible() -> None:
    release = _release(released_at=datetime(2026, 6, 10, 12, 30, tzinfo=UTC))
    late_forecast = _forecast(
        release,
        available_at=release.released_at + timedelta(seconds=1),
    )

    result = calculate_economic_surprises(
        [release],
        [late_forecast],
        as_of=release.released_at + timedelta(hours=1),
    )

    assert result.calculations == ()
    assert result.exclusions[0]["reason"] == "NO_ELIGIBLE_PRE_RELEASE_FORECAST"


def test_original_release_uses_latest_eligible_consensus_and_revision_is_ignored() -> None:
    released_at = datetime(2026, 6, 10, 12, 30, tzinfo=UTC)
    original = _release(released_at=released_at)
    revision = _release(
        released_at=released_at + timedelta(days=30),
        actual=0.25,
        is_revision=True,
    )
    older = _forecast(original, value=0.4)
    latest = _forecast(
        original,
        value=0.3,
        available_at=released_at - timedelta(minutes=5),
    )

    result = calculate_economic_surprises(
        [original, revision],
        [older, latest],
        as_of=released_at + timedelta(days=31),
    )

    assert len(result.calculations) == 1
    surprise = result.calculations[0]
    assert surprise.forecast_id == latest.forecast_id
    assert surprise.raw_surprise == pytest.approx(-0.1)
    assert surprise.gold_direction > 0
    assert surprise.epistemic_status == "INFERRED"


def test_year_over_year_wage_surprise_is_supported_and_gold_signed() -> None:
    released_at = datetime(2026, 6, 10, 12, 30, tzinfo=UTC)
    release = _release(
        released_at=released_at,
        actual=4.0,
        component="AVERAGE_HOURLY_EARNINGS_YOY",
    )
    forecast = _forecast(release, value=3.8)

    result = calculate_economic_surprises(
        [release],
        [forecast],
        as_of=released_at + timedelta(minutes=1),
    )

    assert result.exclusions == ()
    assert len(result.calculations) == 1
    surprise = result.calculations[0]
    assert surprise.raw_surprise == pytest.approx(0.2)
    assert surprise.gold_direction < 0
    assert "stronger wage growth" in surprise.explanation


def test_surprise_standardization_uses_prior_releases_only() -> None:
    start = datetime(2025, 1, 10, 13, 30, tzinfo=UTC)
    releases = [
        _release(
            released_at=start + timedelta(days=30 * index),
            actual=0.2 + index / 100,
        )
        for index in range(7)
    ]
    forecasts = [_forecast(release, value=0.2) for release in releases]
    cutoff = releases[5].released_at + timedelta(minutes=1)

    first = calculate_economic_surprises(
        releases[:6],
        forecasts[:6],
        as_of=cutoff,
    )
    with_unavailable_future = calculate_economic_surprises(
        releases,
        forecasts,
        as_of=cutoff,
    )

    assert len(first.calculations) == 6
    assert first.calculations[-1].history_count == 5
    assert first.calculations[-1].method == "EXPANDING_PRIOR_STD"
    assert first.calculations[-1].data_hash == with_unavailable_future.calculations[-1].data_hash


def test_event_reaction_uses_pre_release_reference_and_marks_reversal() -> None:
    released_at = datetime(2026, 6, 10, 12, 30, tzinfo=UTC)
    release = _release(released_at=released_at)
    forecast = _forecast(release)
    surprise = calculate_economic_surprises(
        [release],
        [forecast],
        as_of=released_at + timedelta(hours=1),
    ).calculations[0]
    bars: list[ReactionBar] = []
    for offset in range(-1, 16):
        open_time = released_at + timedelta(minutes=offset)
        close = 2400.0
        if offset == 0:
            close = 2402.0
        elif offset > 0:
            close = 2399.0
        bars.append(
            ReactionBar(
                open_time=open_time,
                close_time=open_time + timedelta(minutes=1),
                open=2400.0,
                high=max(2400.5, close),
                low=min(2399.5, close),
                close=close,
                available_at=open_time + timedelta(minutes=1),
                source_record_key=open_time.isoformat(),
                is_synthetic=False,
            )
        )

    result = calculate_event_reactions(
        surprise,
        bars,
        study_as_of=released_at + timedelta(minutes=16),
    )

    by_horizon = {reaction.horizon_code: reaction for reaction in result.reactions}
    assert by_horizon["1M"].reference_time == released_at
    assert by_horizon["1M"].first_move_direction == "UP"
    assert by_horizon["5M"].first_move_held is False
    assert by_horizon["15M"].horizon_time == released_at + timedelta(minutes=15)


def test_bundle_schema_rejects_consensus_timestamped_after_release() -> None:
    payload = {
        "provider_code": "MANUAL_EVENT_UPLOAD",
        "is_synthetic": False,
        "events": [
            {
                "event_code": "US_CPI",
                "name": "US Consumer Price Index",
                "event_type": "CPI",
                "scheduled_at": "2026-06-10T12:30:00Z",
                "released_at": "2026-06-10T12:30:00Z",
                "importance": 5,
                "is_scheduled": True,
                "status": "RELEASED",
                "source_event_key": "us-cpi-2026-06",
                "available_at": "2026-06-01T12:00:00Z",
                "forecasts": [
                    {
                        "component_code": "CPI_CORE_MOM",
                        "forecast_value": 0.3,
                        "unit": "PERCENT",
                        "forecast_as_of": "2026-06-10T12:31:00Z",
                        "available_at": "2026-06-10T12:31:00Z",
                        "vintage": "late",
                    }
                ],
                "releases": [
                    {
                        "component_code": "CPI_CORE_MOM",
                        "observation_period": "2026-05-01",
                        "actual_value": 0.2,
                        "unit": "PERCENT",
                        "released_at": "2026-06-10T12:30:00Z",
                        "available_at": "2026-06-10T12:30:02Z",
                        "vintage": "original",
                    }
                ],
            }
        ],
    }

    with pytest.raises(ValidationError, match="must not be after the release"):
        EconomicEventBundleRequest.model_validate(payload)


def test_bundle_schema_accepts_timestamped_fed_metadata_release() -> None:
    payload = {
        "provider_code": "FEDERAL_RESERVE_RSS",
        "dataset_code": "FED_COMMUNICATIONS",
        "is_synthetic": False,
        "events": [
            {
                "event_code": "FOMC_STATEMENT",
                "name": "Federal Reserve issues FOMC statement",
                "event_type": "FOMC_STATEMENT",
                "scheduled_at": "2026-06-17T18:00:00Z",
                "released_at": "2026-06-17T18:00:00Z",
                "importance": 5,
                "is_scheduled": False,
                "status": "RELEASED",
                "source_event_key": (
                    "https://www.federalreserve.gov/newsevents/"
                    "pressreleases/monetary20260617a.htm"
                ),
                "available_at": "2026-06-17T18:00:00Z",
                "forecasts": [],
                "releases": [],
                "metadata": {
                    "time_semantics": "RSS_PUBLICATION_TIMESTAMP",
                    "directional_interpretation": "UNKNOWN",
                },
            }
        ],
    }

    bundle = EconomicEventBundleRequest.model_validate(payload)

    assert bundle.events[0].status == "RELEASED"
    assert bundle.events[0].releases == []


def test_bundle_schema_still_rejects_numeric_release_without_release_fact() -> None:
    payload = {
        "provider_code": "MANUAL_EVENT_UPLOAD",
        "is_synthetic": False,
        "events": [
            {
                "event_code": "US_CPI",
                "name": "US Consumer Price Index",
                "event_type": "CPI",
                "scheduled_at": "2026-06-10T12:30:00Z",
                "released_at": "2026-06-10T12:30:00Z",
                "importance": 5,
                "is_scheduled": True,
                "status": "RELEASED",
                "source_event_key": "us-cpi-2026-06-missing-release",
                "available_at": "2026-06-01T12:00:00Z",
                "forecasts": [],
                "releases": [],
            }
        ],
    }

    with pytest.raises(ValidationError, match="require an original release"):
        EconomicEventBundleRequest.model_validate(payload)
