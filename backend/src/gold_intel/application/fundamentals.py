from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.analytics.fundamentals import (
    FUNDAMENTAL_RULESET_VERSION,
    CotFundamentalPoint,
    EventSurprisePoint,
    FundamentalEventPoint,
    FundamentalObservation,
    FundamentalState,
    PolicyPathFundamentalPoint,
    QuarterlyPolicyExpectationPoint,
    calculate_fundamental_state,
)
from gold_intel.domain.factors import registry_hash
from gold_intel.infrastructure.models import (
    CotPosition,
    CotReport,
    EconomicEvent,
    EconomicSurprise,
    FundamentalSnapshot,
    Observation,
    PolicyExpectationWindow,
    PolicyPathPoint,
)
from gold_intel.providers.alfred import ALFRED_MACRO_SERIES
from gold_intel.providers.public_data import (
    CFTC_GOLD_CONTRACT_CODE,
    FRED_MARKET_SERIES,
)

FUNDAMENTAL_SERIES_CODES = tuple(
    specification.internal_code for specification in FRED_MARKET_SERIES
) + tuple(specification.internal_code for specification in ALFRED_MACRO_SERIES)


@dataclass(frozen=True, slots=True)
class FundamentalInputs:
    observations: tuple[FundamentalObservation, ...]
    cot_points: tuple[CotFundamentalPoint, ...]
    event_surprises: tuple[EventSurprisePoint, ...]
    events: tuple[FundamentalEventPoint, ...]
    policy_path_points: tuple[PolicyPathFundamentalPoint, ...]
    quarterly_policy_expectations: tuple[QuarterlyPolicyExpectationPoint, ...]

    def state_at(
        self,
        as_of: datetime,
        *,
        compute_data_hash: bool = True,
    ) -> FundamentalState:
        return calculate_fundamental_state(
            list(self.observations),
            list(self.cot_points),
            as_of=as_of,
            event_surprises=list(self.event_surprises),
            events=list(self.events),
            policy_path_points=list(self.policy_path_points),
            quarterly_policy_expectations=list(self.quarterly_policy_expectations),
            compute_data_hash=compute_data_hash,
        )

    def provenance_at(self, as_of: datetime) -> dict[str, Any]:
        eligible_quarterly = [
            point
            for point in self.quarterly_policy_expectations
            if point.available_at <= as_of and point.snapshot_as_of <= as_of
        ]
        eligible_meeting_paths = [
            point
            for point in self.policy_path_points
            if point.available_at <= as_of and point.snapshot_as_of <= as_of
        ]
        return {
            "data_mode": "REAL_ONLY",
            "synthetic_records_eligible": False,
            "observed_series_count": len(
                {
                    point.series_code
                    for point in self.observations
                    if point.available_at <= as_of
                    and point.observation_time <= as_of
                }
            ),
            "cot_report_count": sum(
                point.publication_at <= as_of for point in self.cot_points
            ),
            "event_surprise_count": sum(
                point.available_at <= as_of and point.released_at <= as_of
                for point in self.event_surprises
            ),
            "exact_meeting_probability_providers": sorted(
                {point.provider_code for point in eligible_meeting_paths}
            ),
            "quarterly_sofr_distribution_providers": sorted(
                {point.provider_code for point in eligible_quarterly}
            ),
            "quarterly_sofr_window_count": len(eligible_quarterly),
            "quarterly_sofr_observation_range": (
                [
                    min(point.observation_date for point in eligible_quarterly).isoformat(),
                    max(point.observation_date for point in eligible_quarterly).isoformat(),
                ]
                if eligible_quarterly
                else None
            ),
            "expectations_semantics": (
                "Quarterly SOFR distributions are real market-implied estimates "
                "and are not labelled as exact FOMC meeting probabilities."
            ),
        }


async def load_fundamental_inputs(
    session: AsyncSession,
    *,
    as_of: datetime,
) -> FundamentalInputs:
    """Load only evidence that was available by ``as_of``.

    The evaluator applies the availability filter again for every historical
    decision. Keeping the check at both boundaries makes accidental future-data
    access fail closed when this loader is reused.
    """

    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    cutoff = as_of.astimezone(UTC)
    observation_rows = list(
        (
            await session.scalars(
                select(Observation)
                .where(
                    Observation.series_code.in_(FUNDAMENTAL_SERIES_CODES),
                    Observation.available_at <= cutoff,
                    Observation.observation_time <= cutoff,
                    Observation.is_synthetic.is_(False),
                )
                .order_by(
                    Observation.series_code,
                    Observation.observation_time,
                    Observation.available_at,
                )
            )
        ).all()
    )
    observations = tuple(
        FundamentalObservation(
            series_code=row.series_code,
            observation_time=row.observation_time,
            available_at=row.available_at,
            value=float(row.value),
            source_record_key=row.source_record_key,
        )
        for row in observation_rows
    )

    reports = list(
        (
            await session.scalars(
                select(CotReport)
                .where(
                    CotReport.contract_market_code == CFTC_GOLD_CONTRACT_CODE,
                    CotReport.publication_at <= cutoff,
                )
                .order_by(CotReport.publication_at, CotReport.observation_date)
            )
        ).all()
    )
    report_ids = [report.id for report in reports]
    positions_by_report: dict[Any, dict[str, CotPosition]] = {}
    if report_ids:
        positions = list(
            (
                await session.scalars(
                    select(CotPosition).where(CotPosition.report_id.in_(report_ids))
                )
            ).all()
        )
        for position in positions:
            positions_by_report.setdefault(position.report_id, {})[position.category] = position

    cot_points: list[CotFundamentalPoint] = []
    for report in reports:
        categories = positions_by_report.get(report.id, {})
        managed_money = categories.get("MANAGED_MONEY")
        producer = categories.get("PRODUCER_MERCHANT")
        if managed_money is None or producer is None:
            continue
        cot_points.append(
            CotFundamentalPoint(
                observation_date=report.observation_date,
                publication_at=report.publication_at,
                availability_quality=report.availability_quality,
                managed_money_long=managed_money.long_contracts,
                managed_money_short=managed_money.short_contracts,
                producer_long=producer.long_contracts,
                producer_short=producer.short_contracts,
                open_interest=report.open_interest,
                source_record_key=report.source_record_key,
            )
        )

    event_rows = list(
        (
            await session.scalars(
                select(EconomicEvent)
                .where(
                    EconomicEvent.available_at <= cutoff,
                    EconomicEvent.is_synthetic.is_(False),
                )
                .order_by(
                    EconomicEvent.available_at,
                    EconomicEvent.scheduled_at,
                )
            )
        ).all()
    )
    event_by_id = {event.id: event for event in event_rows}
    # Keep every source version. ``calculate_fundamental_state`` selects the
    # latest version whose availability precedes each simulated decision.
    # Canonicalizing here at the research-end cutoff would hide a schedule that
    # was known before a later RELEASED/CANCELLED version arrived.
    events = tuple(
        FundamentalEventPoint(
            event_id=str(event.id),
            event_code=event.event_code,
            event_name=event.name,
            scheduled_at=event.scheduled_at,
            available_at=event.available_at,
            importance=event.importance,
            status=event.status,
            source_record_key=f"{event.provider_code}:{event.source_event_key}",
        )
        for event in event_rows
    )

    surprise_rows = list(
        (
            await session.scalars(
                select(EconomicSurprise)
                .where(
                    EconomicSurprise.available_at <= cutoff,
                    EconomicSurprise.is_synthetic.is_(False),
                )
                .order_by(
                    EconomicSurprise.released_at,
                    EconomicSurprise.history_count.desc(),
                    EconomicSurprise.created_at.desc(),
                )
            )
        ).all()
    )
    canonical_surprises: dict[Any, EconomicSurprise] = {}
    for surprise in surprise_rows:
        canonical_surprises.setdefault(surprise.release_id, surprise)
    event_surprises = tuple(
        EventSurprisePoint(
            event_id=str(surprise.event_id),
            event_code=event_by_id[surprise.event_id].event_code,
            event_name=event_by_id[surprise.event_id].name,
            component_code=surprise.component_code,
            released_at=surprise.released_at,
            available_at=surprise.available_at,
            gold_direction=float(surprise.gold_direction),
            strength=float(surprise.strength),
            confidence=float(surprise.confidence),
            importance=event_by_id[surprise.event_id].importance,
            epistemic_status=surprise.epistemic_status,
            data_hash=surprise.data_hash,
        )
        for surprise in canonical_surprises.values()
        if surprise.event_id in event_by_id
    )
    policy_rows = list(
        (
            await session.scalars(
                select(PolicyPathPoint)
                .where(
                    PolicyPathPoint.available_at <= cutoff,
                    PolicyPathPoint.snapshot_as_of <= cutoff,
                    PolicyPathPoint.is_synthetic.is_(False),
                )
                .order_by(
                    PolicyPathPoint.available_at,
                    PolicyPathPoint.snapshot_as_of,
                    PolicyPathPoint.meeting_date,
                )
            )
        ).all()
    )
    policy_path_points = tuple(
        PolicyPathFundamentalPoint(
            provider_code=row.provider_code,
            snapshot_as_of=row.snapshot_as_of,
            meeting_date=row.meeting_date,
            outcome_basis_points=row.outcome_basis_points,
            probability=float(row.probability),
            expected_rate=(float(row.expected_rate) if row.expected_rate is not None else None),
            available_at=row.available_at,
            source_record_key=row.source_record_key,
        )
        for row in policy_rows
    )
    quarterly_rows = list(
        (
            await session.scalars(
                select(PolicyExpectationWindow)
                .where(
                    PolicyExpectationWindow.available_at <= cutoff,
                    PolicyExpectationWindow.snapshot_as_of <= cutoff,
                    PolicyExpectationWindow.is_synthetic.is_(False),
                )
                .order_by(
                    PolicyExpectationWindow.available_at,
                    PolicyExpectationWindow.snapshot_as_of,
                    PolicyExpectationWindow.reference_start,
                )
            )
        ).all()
    )
    quarterly_policy_expectations = tuple(
        QuarterlyPolicyExpectationPoint(
            provider_code=row.provider_code,
            observation_date=row.observation_date,
            snapshot_as_of=row.snapshot_as_of,
            reference_start=row.reference_start,
            reference_end=row.reference_end,
            rate_p25_basis_points=float(row.rate_p25_basis_points),
            rate_mean_basis_points=float(row.rate_mean_basis_points),
            rate_mode_basis_points=float(row.rate_mode_basis_points),
            rate_p75_basis_points=float(row.rate_p75_basis_points),
            probability_cut=(
                float(row.probability_cut) if row.probability_cut is not None else None
            ),
            probability_hike=(
                float(row.probability_hike) if row.probability_hike is not None else None
            ),
            probability_bins=tuple(row.probability_bins),
            available_at=row.available_at,
            availability_quality=row.availability_quality,
            source_record_key=row.source_record_key,
        )
        for row in quarterly_rows
    )
    return FundamentalInputs(
        observations=observations,
        cot_points=tuple(cot_points),
        event_surprises=event_surprises,
        events=events,
        policy_path_points=policy_path_points,
        quarterly_policy_expectations=quarterly_policy_expectations,
    )


async def calculate_and_store_fundamental_snapshot(
    session: AsyncSession,
    *,
    instrument: str,
    as_of: datetime,
) -> tuple[FundamentalSnapshot, FundamentalState, bool]:
    inputs = await load_fundamental_inputs(session, as_of=as_of)
    state = inputs.state_at(as_of)
    existing = await session.scalar(
        select(FundamentalSnapshot).where(
            FundamentalSnapshot.instrument_code == instrument,
            FundamentalSnapshot.as_of == state.as_of,
            FundamentalSnapshot.ruleset_version == FUNDAMENTAL_RULESET_VERSION,
            FundamentalSnapshot.data_hash == state.data_hash,
        )
    )
    if existing is not None:
        return existing, state, False

    model = FundamentalSnapshot(
        instrument_code=instrument,
        as_of=state.as_of,
        directional_score=Decimal(str(state.directional_score)),
        confidence=Decimal(str(state.confidence)),
        coverage=Decimal(str(state.coverage)),
        bias_label=state.bias_label,
        regime_label=state.regime_label,
        reaction_function=state.reaction_function,
        dominant_driver=state.dominant_driver,
        main_contradiction=state.main_contradiction,
        event_risk=state.event_risk,
        upcoming_catalyst=state.upcoming_catalyst,
        components=[asdict(component) for component in state.components],
        layers=list(state.layers),
        reasoning=state.reasoning,
        registry_hash=registry_hash(),
        data_hash=state.data_hash,
        ruleset_version=FUNDAMENTAL_RULESET_VERSION,
    )
    session.add(model)
    await session.flush()
    return model, state, True


def snapshot_to_dict(snapshot: FundamentalSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "instrument": snapshot.instrument_code,
        "as_of": snapshot.as_of,
        "directional_score": float(snapshot.directional_score),
        "confidence": float(snapshot.confidence),
        "coverage": float(snapshot.coverage),
        "bias": snapshot.bias_label,
        "regime": snapshot.regime_label,
        "reaction_function": snapshot.reaction_function,
        "dominant_driver": snapshot.dominant_driver,
        "main_contradiction": snapshot.main_contradiction,
        "event_risk": snapshot.event_risk,
        "upcoming_catalyst": snapshot.upcoming_catalyst,
        "components": snapshot.components,
        "layers": snapshot.layers,
        "reasoning": snapshot.reasoning,
        "registry_hash": snapshot.registry_hash,
        "data_hash": snapshot.data_hash,
        "ruleset_version": snapshot.ruleset_version,
        "created_at": snapshot.created_at,
    }
