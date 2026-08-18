from datetime import UTC, date, datetime, timedelta

from gold_intel.analytics.fundamentals import (
    DRIVER_WEIGHTS,
    CotFundamentalPoint,
    EventSurprisePoint,
    FundamentalEventPoint,
    FundamentalObservation,
    PolicyPathFundamentalPoint,
    QuarterlyPolicyExpectationPoint,
    calculate_fundamental_state,
)
from gold_intel.domain.factors import FACTOR_BY_CODE, FACTOR_REGISTRY
from gold_intel.providers.public_data import cot_publication_at


def _observations(*, include_future: bool = False) -> list[FundamentalObservation]:
    start = datetime(2026, 1, 1, 16, 0, tzinfo=UTC)
    values = {
        "US_REAL_YIELD_10Y": [2.0, 1.96, 1.92, 1.88, 1.84, 1.80],
        "USD_BROAD_NOMINAL": [100.0, 99.9, 99.8, 99.7, 99.6, 99.5],
        "US_TREASURY_2Y": [4.5, 4.45, 4.4, 4.35, 4.3, 4.25],
        "US_TREASURY_10Y": [4.5, 4.48, 4.46, 4.44, 4.42, 4.4],
        "US_BREAKEVEN_10Y": [2.5, 2.52, 2.54, 2.56, 2.58, 2.6],
    }
    output: list[FundamentalObservation] = []
    for series_code, series_values in values.items():
        for offset, value in enumerate(series_values):
            observation_time = start + timedelta(days=offset)
            output.append(
                FundamentalObservation(
                    series_code=series_code,
                    observation_time=observation_time,
                    available_at=observation_time + timedelta(hours=8),
                    value=value,
                    source_record_key=f"{series_code}:{offset}",
                )
            )
    if include_future:
        output.append(
            FundamentalObservation(
                series_code="US_REAL_YIELD_10Y",
                observation_time=datetime(2026, 1, 7, 16, 0, tzinfo=UTC),
                available_at=datetime(2026, 1, 11, 0, 0, tzinfo=UTC),
                value=99.0,
                source_record_key="FUTURE_REVISION",
            )
        )
    return output


def _cot_points() -> list[CotFundamentalPoint]:
    return [
        CotFundamentalPoint(
            observation_date=date(2025, 12, 23),
            publication_at=datetime(2025, 12, 26, 20, 30, tzinfo=UTC),
            availability_quality="ESTIMATED_STANDARD_FRIDAY",
            managed_money_long=200_000,
            managed_money_short=80_000,
            producer_long=100_000,
            producer_short=250_000,
            open_interest=500_000,
            source_record_key="cot:1",
        ),
        CotFundamentalPoint(
            observation_date=date(2025, 12, 30),
            publication_at=datetime(2026, 1, 5, 20, 30, tzinfo=UTC),
            availability_quality="EXACT_OFFICIAL_SCHEDULE",
            managed_money_long=210_000,
            managed_money_short=75_000,
            producer_long=95_000,
            producer_short=260_000,
            open_interest=510_000,
            source_record_key="cot:2",
        ),
    ]


def _vintage_macro_observations() -> list[FundamentalObservation]:
    output: list[FundamentalObservation] = []
    monthly_start = datetime(2024, 1, 1, tzinfo=UTC)
    monthly_series = {
        "US_CPI_HEADLINE": (100.0, 0.0040, 0.0015),
        "US_CPI_CORE": (100.0, 0.0038, 0.0016),
        "US_PCE_HEADLINE": (100.0, 0.0035, 0.0013),
        "US_PCE_CORE": (100.0, 0.0036, 0.0015),
        "US_RETAIL_SALES": (700_000.0, 0.0050, 0.0010),
        "US_AVERAGE_HOURLY_EARNINGS": (30.0, 0.0040, 0.0015),
    }
    for series_code, (initial, early_growth, late_growth) in monthly_series.items():
        value = initial
        for offset in range(18):
            observed = monthly_start + timedelta(days=30 * offset)
            output.append(
                FundamentalObservation(
                    series_code=series_code,
                    observation_time=observed,
                    available_at=observed + timedelta(days=40),
                    value=value,
                    source_record_key=f"{series_code}:{offset}",
                )
            )
            value *= 1 + (early_growth if offset < 6 else late_growth)

    payroll = 150_000.0
    for offset in range(18):
        observed = monthly_start + timedelta(days=30 * offset)
        payroll += 250 if offset < 9 else 80
        output.append(
            FundamentalObservation(
                series_code="US_NONFARM_PAYROLLS",
                observation_time=observed,
                available_at=observed + timedelta(days=40),
                value=payroll,
                source_record_key=f"PAYROLL:{offset}",
            )
        )
        output.append(
            FundamentalObservation(
                series_code="US_UNEMPLOYMENT_RATE",
                observation_time=observed,
                available_at=observed + timedelta(days=40),
                value=3.5 + max(0, offset - 8) * 0.06,
                source_record_key=f"UNRATE:{offset}",
            )
        )

    gdp = 20_000.0
    quarterly_start = datetime(2024, 1, 1, tzinfo=UTC)
    for offset, growth in enumerate((0.010, 0.009, 0.008, 0.005, 0.002, -0.002)):
        gdp *= 1 + growth
        observed = quarterly_start + timedelta(days=91 * offset)
        output.append(
            FundamentalObservation(
                series_code="US_REAL_GDP",
                observation_time=observed,
                available_at=observed + timedelta(days=50),
                value=gdp,
                source_record_key=f"GDP:{offset}",
            )
        )

    claims_start = datetime(2025, 3, 1, tzinfo=UTC)
    for offset in range(20):
        observed = claims_start + timedelta(days=7 * offset)
        output.append(
            FundamentalObservation(
                series_code="US_INITIAL_JOBLESS_CLAIMS",
                observation_time=observed,
                available_at=observed + timedelta(days=7),
                value=200_000 + offset * 2_500,
                source_record_key=f"CLAIMS:{offset}",
            )
        )
    return output


def test_driver_budget_is_complete_and_factor_registry_is_unique() -> None:
    assert sum(DRIVER_WEIGHTS.values()) == 100
    codes = [factor.code for factor in FACTOR_REGISTRY]
    assert len(codes) == len(set(codes))
    assert {factor.layer for factor in FACTOR_REGISTRY if factor.layer} == set(range(1, 8))
    assert FACTOR_BY_CODE["FED_FIRST_MOVE_TIMING"].dependencies == (
        "FED_NEXT_MEETING_PROBABILITY",
    )
    assert FACTOR_BY_CODE["FED_PATH_REPRICING"].dependency_mode == "ANY"
    assert "FED_QUARTERLY_SOFR_EXPECTATIONS" in (
        FACTOR_BY_CODE["FED_PATH_REPRICING"].dependencies
    )
    assert FACTOR_BY_CODE["RISK_BASED_POSITION_SIZE"].implementation_status == "CONTRACT"


def test_fundamental_state_is_point_in_time_and_missing_factors_remain_unknown() -> None:
    as_of = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    without_future = calculate_fundamental_state(
        _observations(),
        _cot_points(),
        as_of=as_of,
    )
    with_future = calculate_fundamental_state(
        _observations(include_future=True),
        _cot_points(),
        as_of=as_of,
    )

    assert without_future.data_hash == with_future.data_hash
    assert without_future.directional_score == with_future.directional_score
    assert without_future.directional_score > 0
    assert without_future.coverage == 46
    assert without_future.reasoning["weight_profile"] == "BASE"
    components = {component.code: component for component in without_future.components}
    assert components["INFLATION_REGIME"].epistemic_status == "UNKNOWN"
    assert components["CATALYST_SURPRISE"].epistemic_status == "UNKNOWN"
    assert "FUTURE_REVISION" not in str(with_future.reasoning)


def test_permission_requires_direction_coverage_and_confidence() -> None:
    state = calculate_fundamental_state(
        _observations(),
        _cot_points(),
        as_of=datetime(2026, 1, 10, 12, 0, tzinfo=UTC),
    )

    permitted, reason = state.permission(
        "LONG",
        minimum_score=1,
        minimum_coverage=40,
        minimum_confidence=1,
    )
    assert permitted
    assert reason == "FUNDAMENTALS_ALIGNED"

    permitted, reason = state.permission(
        "SHORT",
        minimum_score=1,
        minimum_coverage=40,
        minimum_confidence=1,
    )
    assert not permitted
    assert reason == "FUNDAMENTALS_NOT_BEARISH_ENOUGH"


def test_event_surprise_is_point_in_time_and_upcoming_catalyst_reduces_confidence() -> None:
    as_of = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    surprise = EventSurprisePoint(
        event_id="event-1",
        event_code="US_CPI",
        event_name="US Consumer Price Index",
        component_code="CPI_CORE_MOM",
        released_at=as_of - timedelta(hours=1),
        available_at=as_of - timedelta(hours=1) + timedelta(seconds=2),
        gold_direction=1,
        strength=100,
        confidence=90,
        importance=5,
        epistemic_status="INFERRED",
        data_hash="surprise-hash",
    )
    upcoming = FundamentalEventPoint(
        event_id="event-2",
        event_code="US_NFP",
        event_name="US Nonfarm Payrolls",
        scheduled_at=as_of + timedelta(hours=2),
        available_at=as_of - timedelta(days=7),
        importance=5,
        status="SCHEDULED",
        source_record_key="calendar:nfp-2026-01",
    )
    without_upcoming = calculate_fundamental_state(
        _observations(),
        _cot_points(),
        as_of=as_of,
        event_surprises=[surprise],
    )
    with_upcoming = calculate_fundamental_state(
        _observations(),
        _cot_points(),
        as_of=as_of,
        event_surprises=[surprise],
        events=[upcoming],
    )

    component = {item.code: item for item in with_upcoming.components}["CATALYST_SURPRISE"]
    assert component.epistemic_status == "INFERRED"
    assert with_upcoming.coverage == 54
    assert with_upcoming.event_risk == "HIGH"
    assert with_upcoming.upcoming_catalyst is not None
    assert with_upcoming.confidence < without_upcoming.confidence


def test_later_event_version_cannot_hide_schedule_known_at_prior_decision() -> None:
    as_of = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    scheduled = FundamentalEventPoint(
        event_id="scheduled-version",
        event_code="US_CPI",
        event_name="US Consumer Price Index",
        scheduled_at=as_of + timedelta(hours=2),
        available_at=as_of - timedelta(days=5),
        importance=5,
        status="SCHEDULED",
        source_record_key="calendar:cpi-2026-01",
    )
    released = FundamentalEventPoint(
        event_id="released-version",
        event_code="US_CPI",
        event_name="US Consumer Price Index",
        scheduled_at=scheduled.scheduled_at,
        available_at=scheduled.scheduled_at + timedelta(seconds=2),
        importance=5,
        status="RELEASED",
        source_record_key=scheduled.source_record_key,
    )

    state = calculate_fundamental_state(
        _observations(),
        _cot_points(),
        as_of=as_of,
        events=[scheduled, released],
    )

    assert state.event_risk == "HIGH"
    assert state.upcoming_catalyst is not None
    assert state.upcoming_catalyst["event_id"] == "scheduled-version"


def test_vintage_macro_levels_activate_level_direction_and_rate_of_change_regimes() -> None:
    observations = _vintage_macro_observations()
    as_of = max(point.available_at for point in observations) + timedelta(days=5)
    state = calculate_fundamental_state(
        observations,
        [],
        as_of=as_of,
    )

    components = {component.code: component for component in state.components}
    assert components["INFLATION_REGIME"].epistemic_status == "CALCULATED"
    assert components["GROWTH_REGIME"].epistemic_status == "CALCULATED"
    assert components["LABOUR_REGIME"].epistemic_status == "CALCULATED"
    assert (
        components["INFLATION_REGIME"].evidence["weighted_yoy_pct"]
        != components["INFLATION_REGIME"].evidence["three_month_yoy_change_pp"]
    )
    assert state.coverage == 26
    assert state.regime_label in {
        "SOFT_LANDING",
        "SLOWDOWN",
        "RECESSION_DISINFLATION",
        "GOLDILOCKS",
    }
    assert state.reaction_function != "UNKNOWN_WITHOUT_EVENT_AND_REGIME_CORE"


def test_complete_fed_path_uses_repricing_destination_and_first_move() -> None:
    as_of = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
    observations = [
        FundamentalObservation(
            series_code="US_FED_FUNDS_EFFECTIVE",
            observation_time=as_of - timedelta(days=2),
            available_at=as_of - timedelta(days=1),
            value=4.5,
            source_record_key="DFF:current",
        )
    ]

    def snapshot(
        at: datetime,
        first: tuple[tuple[int, float], ...],
        second: tuple[tuple[int, float], ...],
    ) -> list[PolicyPathFundamentalPoint]:
        output: list[PolicyPathFundamentalPoint] = []
        for meeting, outcomes in (
            (date(2026, 3, 18), first),
            (date(2026, 6, 17), second),
        ):
            for basis_points, probability in outcomes:
                output.append(
                    PolicyPathFundamentalPoint(
                        provider_code="LICENSED_TEST",
                        snapshot_as_of=at,
                        meeting_date=meeting,
                        outcome_basis_points=basis_points,
                        probability=probability,
                        expected_rate=None,
                        available_at=at + timedelta(seconds=1),
                        source_record_key=(f"{at.isoformat()}:{meeting}:{basis_points}"),
                    )
                )
        return output

    prior = snapshot(
        as_of - timedelta(days=2),
        ((425, 0.7), (450, 0.3)),
        ((400, 0.7), (425, 0.3)),
    )
    latest = snapshot(
        as_of - timedelta(hours=2),
        ((400, 0.7), (425, 0.3)),
        ((350, 0.7), (375, 0.3)),
    )
    future = snapshot(
        as_of + timedelta(hours=1),
        ((500, 1.0),),
        ((550, 1.0),),
    )
    state = calculate_fundamental_state(
        observations,
        [],
        as_of=as_of,
        policy_path_points=prior + latest,
    )
    with_future = calculate_fundamental_state(
        observations,
        [],
        as_of=as_of,
        policy_path_points=prior + latest + future,
    )

    component = {item.code: item for item in state.components}["FED_PATH"]
    assert component.epistemic_status == "CALCULATED"
    assert component.direction > 0
    assert component.evidence["stance"] == "DOVISH_REPRICING"
    assert component.evidence["first_expected_move"] is not None
    assert state.coverage == 18
    assert state.data_hash == with_future.data_hash


def test_real_quarterly_sofr_path_is_used_without_claiming_meeting_probabilities() -> None:
    as_of = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    observations = [
        FundamentalObservation(
            series_code="US_FED_FUNDS_EFFECTIVE",
            observation_time=as_of - timedelta(days=3),
            available_at=as_of - timedelta(days=2),
            value=4.5,
            source_record_key="DFF:current",
        )
    ]

    def snapshot(
        snapshot_as_of: datetime,
        rates: tuple[float, float, float, float],
    ) -> list[QuarterlyPolicyExpectationPoint]:
        starts = (
            date(2026, 9, 16),
            date(2026, 12, 16),
            date(2027, 3, 17),
            date(2027, 6, 16),
        )
        return [
            QuarterlyPolicyExpectationPoint(
                provider_code="ATLANTA_FED_MPT",
                observation_date=snapshot_as_of.date(),
                snapshot_as_of=snapshot_as_of,
                reference_start=start,
                reference_end=start + timedelta(days=89),
                rate_p25_basis_points=rate - 20,
                rate_mean_basis_points=rate,
                rate_mode_basis_points=rate,
                rate_p75_basis_points=rate + 20,
                probability_cut=0.7,
                probability_hike=0.1,
                probability_bins=(
                    {
                        "lower_basis_points": int(rate - 12.5),
                        "upper_basis_points": int(rate + 12.5),
                        "probability": 1.0,
                    },
                ),
                available_at=snapshot_as_of + timedelta(hours=12),
                availability_quality="CONSERVATIVE_NEXT_US_BUSINESS_DAY_END",
                source_record_key=f"MPT:{snapshot_as_of.date()}:{start}",
            )
            for start, rate in zip(starts, rates, strict=True)
        ]

    prior = snapshot(
        as_of - timedelta(days=3),
        (430, 420, 410, 400),
    )
    latest = snapshot(
        as_of - timedelta(days=1),
        (400, 390, 380, 370),
    )
    future = snapshot(
        as_of + timedelta(days=1),
        (500, 510, 520, 530),
    )
    state = calculate_fundamental_state(
        observations,
        [],
        as_of=as_of,
        quarterly_policy_expectations=prior + latest,
    )
    with_future = calculate_fundamental_state(
        observations,
        [],
        as_of=as_of,
        quarterly_policy_expectations=prior + latest + future,
    )

    component = {item.code: item for item in state.components}["FED_PATH"]
    assert component.epistemic_status == "CALCULATED"
    assert component.direction > 0
    assert component.evidence["source_semantics"] == ("QUARTERLY_AVERAGE_SOFR_OPTIONS_DISTRIBUTION")
    assert component.evidence["exact_fomc_meeting_probability"] is False
    assert "not an exact meeting-date" in component.evidence["interpretation_warning"]
    assert state.data_hash == with_future.data_hash


def test_public_risk_proxies_can_identify_financial_stress_without_claiming_flow() -> None:
    start = datetime(2026, 1, 1, 16, 0, tzinfo=UTC)
    observations: list[FundamentalObservation] = []
    for offset in range(6):
        observed = start + timedelta(days=offset)
        observations.extend(
            [
                FundamentalObservation(
                    series_code="US_EQUITY_PROXY",
                    observation_time=observed,
                    available_at=observed + timedelta(hours=8),
                    value=5_000 - offset * 60,
                    source_record_key=f"SP500:{offset}",
                ),
                FundamentalObservation(
                    series_code="US_VOLATILITY_INDEX",
                    observation_time=observed,
                    available_at=observed + timedelta(hours=8),
                    value=15 + offset * 1.5,
                    source_record_key=f"VIX:{offset}",
                ),
                FundamentalObservation(
                    series_code="US_HIGH_YIELD_OAS",
                    observation_time=observed,
                    available_at=observed + timedelta(hours=8),
                    value=3.0 + offset * 0.25,
                    source_record_key=f"HY:{offset}",
                ),
            ]
        )
    observations.extend(
        [
            FundamentalObservation(
                series_code="US_FINANCIAL_STRESS",
                observation_time=start,
                available_at=start + timedelta(hours=8),
                value=0.0,
                source_record_key="STRESS:0",
            ),
            FundamentalObservation(
                series_code="US_FINANCIAL_STRESS",
                observation_time=start + timedelta(days=7),
                available_at=start + timedelta(days=7, hours=8),
                value=0.8,
                source_record_key="STRESS:1",
            ),
        ]
    )
    state = calculate_fundamental_state(
        observations,
        [],
        as_of=start + timedelta(days=8),
    )
    components = {component.code: component for component in state.components}

    assert components["EQUITY_RISK"].epistemic_status == "INFERRED"
    assert components["FINANCIAL_STRESS"].epistemic_status == "INFERRED"
    assert "not observed gold flow" in str(
        components["EQUITY_RISK"].evidence["classification_warning"]
    )
    assert state.coverage == 16
    assert state.reasoning["weight_profile"] == "FINANCIAL_STRESS_FOCUS"
    assert state.regime_label == "FINANCIAL_CRISIS_OR_LIQUIDITY_STRESS"
    assert state.reaction_function == "FINANCIAL_STRESS_FOCUS"


def test_cot_availability_uses_holiday_shifted_official_schedule() -> None:
    publication, quality = cot_publication_at(date(2026, 6, 16))
    assert publication.astimezone().date() >= date(2026, 6, 22)
    assert publication.date() == date(2026, 6, 22)
    assert quality == "EXACT_OFFICIAL_SCHEDULE"

    ordinary, ordinary_quality = cot_publication_at(date(2025, 6, 17))
    assert ordinary.date() == date(2025, 6, 20)
    assert ordinary_quality == "ESTIMATED_STANDARD_FRIDAY"


def test_bulk_research_can_skip_hash_without_changing_decision_state() -> None:
    as_of = datetime(2026, 1, 7, 12, 0, tzinfo=UTC)
    observations = _observations()
    full = calculate_fundamental_state(
        observations,
        _cot_points(),
        as_of=as_of,
    )
    bulk = calculate_fundamental_state(
        observations,
        _cot_points(),
        as_of=as_of,
        compute_data_hash=False,
    )

    assert full.data_hash != "NOT_COMPUTED"
    assert bulk.data_hash == "NOT_COMPUTED"
    assert bulk.directional_score == full.directional_score
    assert bulk.confidence == full.confidence
    assert bulk.coverage == full.coverage
    assert bulk.bias_label == full.bias_label
    assert bulk.regime_label == full.regime_label
    assert bulk.reaction_function == full.reaction_function
    assert bulk.components == full.components
