from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.domain.factors import (
    FACTOR_BY_CODE,
    FACTOR_REGISTRY,
    FACTOR_REGISTRY_VERSION,
    FactorDefinition,
    registry_hash,
)
from gold_intel.infrastructure.models import (
    CotPosition,
    CotReport,
    EconomicEvent,
    EconomicRelease,
    EconomicSurprise,
    EventReaction,
    ForecastSnapshot,
    Observation,
    PolicyExpectationWindow,
    PolicyPathPoint,
    PriceBar,
)


@dataclass(frozen=True, slots=True)
class FactorCoverage:
    code: str
    name: str
    domain: str
    layer: int | None
    declared_epistemic_status: str
    current_epistemic_status: str
    implementation_status: str
    phase1_required: bool
    source_class: str
    record_count: int
    latest_available_at: datetime | None
    age_seconds: int | None
    freshness_status: str
    usable_now: bool
    dependencies: tuple[str, ...]
    dependency_mode: str
    missing_dependencies: tuple[str, ...]
    note: str


@dataclass(frozen=True, slots=True)
class CoverageReport:
    as_of: datetime
    registry_version: str
    registry_hash: str
    total_factors: int
    known_factors: int
    phase1_required_factors: int
    phase1_known_factors: int
    phase1_coverage_pct: float
    book_layer_factors: int
    book_layer_known_factors: int
    book_layer_usable_factors: int
    book_factor_coverage_pct: float
    book_usable_coverage_pct: float
    layers: list[dict[str, Any]]
    factors: list[FactorCoverage]


async def build_coverage_report(session: AsyncSession, *, as_of: datetime) -> CoverageReport:
    series_rows = (
        await session.execute(
            select(
                Observation.series_code,
                func.count(Observation.id),
                func.max(Observation.available_at),
            )
            .where(
                Observation.available_at <= as_of,
                Observation.is_synthetic.is_(False),
            )
            .group_by(Observation.series_code)
        )
    ).all()
    series_stats = {str(code): (int(count), latest) for code, count, latest in series_rows}
    price_count, price_latest = (
        await session.execute(
            select(func.count(PriceBar.id), func.max(PriceBar.available_at)).where(
                PriceBar.instrument_code == "XAUUSD",
                PriceBar.available_at <= as_of,
                PriceBar.is_synthetic.is_(False),
            )
        )
    ).one()
    spread_count, spread_latest = (
        await session.execute(
            select(
                func.count(PriceBar.id),
                func.max(PriceBar.available_at),
            ).where(
                PriceBar.instrument_code == "XAUUSD",
                PriceBar.available_at <= as_of,
                PriceBar.spread_points.is_not(None),
                PriceBar.is_synthetic.is_(False),
            )
        )
    ).one()
    tick_volume_count, tick_volume_latest = (
        await session.execute(
            select(
                func.count(PriceBar.id),
                func.max(PriceBar.available_at),
            ).where(
                PriceBar.instrument_code == "XAUUSD",
                PriceBar.available_at <= as_of,
                PriceBar.volume.is_not(None),
                PriceBar.volume_type == "TICK",
                PriceBar.is_synthetic.is_(False),
            )
        )
    ).one()
    cot_count, cot_latest = (
        await session.execute(
            select(func.count(CotReport.id), func.max(CotReport.publication_at)).where(
                CotReport.contract_market_code == "088691",
                CotReport.publication_at <= as_of,
            )
        )
    ).one()
    managed_money_count = await session.scalar(
        select(func.count(CotPosition.id))
        .join(CotReport, CotReport.id == CotPosition.report_id)
        .where(
            CotPosition.category == "MANAGED_MONEY",
            CotReport.publication_at <= as_of,
        )
    )
    event_count, event_latest = (
        await session.execute(
            select(
                func.count(EconomicEvent.id),
                func.max(EconomicEvent.available_at),
            ).where(
                EconomicEvent.available_at <= as_of,
                EconomicEvent.is_scheduled.is_(True),
                EconomicEvent.is_synthetic.is_(False),
            )
        )
    ).one()
    treasury_auction_count, treasury_auction_latest = (
        await session.execute(
            select(
                func.count(EconomicEvent.id),
                func.max(EconomicEvent.available_at),
            ).where(
                EconomicEvent.provider_code == "US_TREASURY_FISCAL_DATA",
                EconomicEvent.event_type == "TREASURY_AUCTION",
                EconomicEvent.available_at <= as_of,
                EconomicEvent.is_synthetic.is_(False),
            )
        )
    ).one()
    fed_communication_count, fed_communication_latest = (
        await session.execute(
            select(
                func.count(EconomicEvent.id),
                func.max(EconomicEvent.available_at),
            ).where(
                EconomicEvent.provider_code == "FEDERAL_RESERVE_RSS",
                EconomicEvent.event_type.in_(
                    (
                        "FED_SPEECH",
                        "FED_TESTIMONY",
                        "FED_MONETARY_POLICY_RELEASE",
                        "FOMC_MINUTES",
                        "FOMC_PROJECTIONS",
                        "FOMC_STATEMENT",
                    )
                ),
                EconomicEvent.available_at <= as_of,
                EconomicEvent.is_synthetic.is_(False),
            )
        )
    ).one()
    forecast_count, forecast_latest = (
        await session.execute(
            select(
                func.count(ForecastSnapshot.id),
                func.max(ForecastSnapshot.available_at),
            ).where(
                ForecastSnapshot.available_at <= as_of,
                ForecastSnapshot.is_synthetic.is_(False),
            )
        )
    ).one()
    release_count, release_latest = (
        await session.execute(
            select(
                func.count(EconomicRelease.id),
                func.max(EconomicRelease.available_at),
            ).where(
                EconomicRelease.available_at <= as_of,
                EconomicRelease.is_synthetic.is_(False),
            )
        )
    ).one()
    revision_count, revision_latest = (
        await session.execute(
            select(
                func.count(EconomicRelease.id),
                func.max(EconomicRelease.available_at),
            ).where(
                EconomicRelease.available_at <= as_of,
                or_(
                    EconomicRelease.is_revision.is_(True),
                    EconomicRelease.revised_previous_value.is_not(None),
                ),
                EconomicRelease.is_synthetic.is_(False),
            )
        )
    ).one()
    surprise_count, surprise_latest = (
        await session.execute(
            select(
                func.count(EconomicSurprise.id),
                func.max(EconomicSurprise.available_at),
            ).where(
                EconomicSurprise.available_at <= as_of,
                EconomicSurprise.is_synthetic.is_(False),
            )
        )
    ).one()
    policy_count, policy_latest = (
        await session.execute(
            select(
                func.count(PolicyPathPoint.id),
                func.max(PolicyPathPoint.available_at),
            ).where(
                PolicyPathPoint.available_at <= as_of,
                PolicyPathPoint.is_synthetic.is_(False),
            )
        )
    ).one()
    quarterly_policy_count, quarterly_policy_latest = (
        await session.execute(
            select(
                func.count(PolicyExpectationWindow.id),
                func.max(PolicyExpectationWindow.available_at),
            ).where(
                PolicyExpectationWindow.available_at <= as_of,
                PolicyExpectationWindow.is_synthetic.is_(False),
            )
        )
    ).one()
    reaction_count, reaction_latest = (
        await session.execute(
            select(
                func.count(EventReaction.id),
                func.max(EventReaction.available_at),
            ).where(
                EventReaction.available_at <= as_of,
                EventReaction.is_synthetic.is_(False),
            )
        )
    ).one()

    direct: dict[str, tuple[int, datetime | None]] = {}
    if price_count:
        direct["XAUUSD_PRICE"] = (int(price_count), price_latest)
        for code in (
            "ASIA_SESSION",
            "LONDON_SESSION",
            "NEW_YORK_SESSION",
            "LONDON_NEW_YORK_OVERLAP",
            "DAILY_ROLLOVER",
            "LBMA_BENCHMARK_WINDOWS",
            "SESSION_RANGE_HANDOVER",
            "SESSION_CLOSE_SQUARING",
            "MULTITIMEFRAME_STRUCTURE",
            "ACCEPTANCE_REJECTION",
            "COMPRESSION_EXPANSION",
        ):
            direct[code] = (int(price_count), price_latest)
    if spread_count:
        direct["BID_ASK_SPREAD"] = (int(spread_count), spread_latest)
    if tick_volume_count:
        direct["TRADED_VOLUME"] = (int(tick_volume_count), tick_volume_latest)
    if cot_count and managed_money_count:
        for code in (
            "COT_MANAGED_MONEY_LONG",
            "COT_MANAGED_MONEY_SHORT",
            "COT_MANAGED_MONEY_NET",
            "COT_POSITIONING_PERCENTILE",
            "COT_PRODUCER_HEDGING",
            "COMEX_OPEN_INTEREST",
        ):
            direct[code] = (int(cot_count), cot_latest)
    if event_count:
        direct["SCHEDULED_EVENT_CALENDAR"] = (int(event_count), event_latest)
    if treasury_auction_count:
        direct["TREASURY_AUCTION_CALENDAR"] = (
            int(treasury_auction_count),
            treasury_auction_latest,
        )
    if fed_communication_count:
        direct["FED_COMMUNICATIONS_RELEASED"] = (
            int(fed_communication_count),
            fed_communication_latest,
        )
    if forecast_count:
        direct["ECONOMIC_CONSENSUS"] = (int(forecast_count), forecast_latest)
    if release_count:
        direct["ACTUAL_VS_PREVIOUS"] = (int(release_count), release_latest)
    if revision_count:
        direct["RELEASE_REVISIONS"] = (int(revision_count), revision_latest)
    if surprise_count:
        direct["ACTUAL_VS_FORECAST"] = (int(surprise_count), surprise_latest)
    if policy_count:
        for code in (
            "FED_NEXT_MEETING_PROBABILITY",
            "FED_FIRST_MOVE_TIMING",
            "FED_TOTAL_EASING_TIGHTENING",
            "FED_TERMINAL_DESTINATION",
            "FED_PATH_REPRICING",
        ):
            direct[code] = (int(policy_count), policy_latest)
    if quarterly_policy_count:
        direct["FED_QUARTERLY_SOFR_EXPECTATIONS"] = (
            int(quarterly_policy_count),
            quarterly_policy_latest,
        )
        for code in (
            "FED_TOTAL_EASING_TIGHTENING",
            "FED_TERMINAL_DESTINATION",
            "FED_PATH_REPRICING",
        ):
            direct[code] = (
                int(quarterly_policy_count),
                quarterly_policy_latest,
            )
    if reaction_count:
        for code in (
            "EVENT_REACTION_HORIZONS",
            "EVENT_MFE_MAE",
            "FIRST_MOVE_HOLD_REVERSAL",
        ):
            direct[code] = (int(reaction_count), reaction_latest)

    resolved: dict[str, FactorCoverage] = {}

    def resolve(definition: FactorDefinition, stack: set[str]) -> FactorCoverage:
        if definition.code in resolved:
            return resolved[definition.code]
        if definition.code in stack:
            raise ValueError(f"Factor dependency cycle at {definition.code}")
        stack = {*stack, definition.code}

        record_count = 0
        latest: datetime | None = None
        direct_known = False
        if definition.series_codes:
            stats = [series_stats.get(code, (0, None)) for code in definition.series_codes]
            direct_known = all(count > 0 for count, _ in stats)
            record_count = min((count for count, _ in stats), default=0)
            latest_values = [item for _, item in stats if item is not None]
            latest = min(latest_values) if latest_values else None
        elif definition.code in direct:
            record_count, latest = direct[definition.code]
            direct_known = record_count > 0

        dependency_rows = [resolve(FACTOR_BY_CODE[code], stack) for code in definition.dependencies]
        unavailable_dependencies = tuple(
            row.code for row in dependency_rows if row.current_epistemic_status == "UNKNOWN"
        )
        if definition.dependency_mode == "ANY":
            dependency_known = any(
                row.current_epistemic_status != "UNKNOWN" for row in dependency_rows
            )
            missing_dependencies = () if dependency_known else unavailable_dependencies
        else:
            missing_dependencies = unavailable_dependencies
            dependency_known = bool(dependency_rows) and not missing_dependencies
        implementation_available = definition.implementation_status in {
            "ACTIVE",
            "PARTIAL",
        }
        known = implementation_available and (direct_known or dependency_known)
        selected_dependencies = [
            row
            for row in dependency_rows
            if row.current_epistemic_status != "UNKNOWN"
        ]
        if not direct_known and selected_dependencies:
            if definition.dependency_mode == "ANY":
                selected = max(
                    selected_dependencies,
                    key=lambda row: row.latest_available_at or datetime.min.replace(
                        tzinfo=as_of.tzinfo
                    ),
                )
                record_count = selected.record_count
                latest = selected.latest_available_at
            else:
                record_count = min(row.record_count for row in selected_dependencies)
                dated = [
                    row.latest_available_at
                    for row in selected_dependencies
                    if row.latest_available_at is not None
                ]
                latest = min(dated) if dated else None
        age_seconds = (
            max(0, int((as_of - latest).total_seconds()))
            if latest is not None
            else None
        )
        dependency_stale = bool(selected_dependencies) and (
            any(row.freshness_status == "STALE" for row in selected_dependencies)
            if definition.dependency_mode == "ALL"
            else all(row.freshness_status == "STALE" for row in selected_dependencies)
        )
        if not known:
            freshness_status = "UNKNOWN"
        elif (
            definition.freshness_seconds is not None
            and age_seconds is not None
            and age_seconds > definition.freshness_seconds
        ) or dependency_stale:
            freshness_status = "STALE"
        elif latest is None:
            freshness_status = "NOT_APPLICABLE"
        else:
            freshness_status = "FRESH"
        usable_now = known and freshness_status != "STALE"
        current_status = definition.epistemic_status if known else "UNKNOWN"
        coverage = FactorCoverage(
            code=definition.code,
            name=definition.name,
            domain=definition.domain,
            layer=definition.layer,
            declared_epistemic_status=definition.epistemic_status,
            current_epistemic_status=current_status,
            implementation_status=definition.implementation_status,
            phase1_required=definition.phase1_required,
            source_class=definition.source_class,
            record_count=record_count,
            latest_available_at=latest,
            age_seconds=age_seconds,
            freshness_status=freshness_status,
            usable_now=usable_now,
            dependencies=definition.dependencies,
            dependency_mode=definition.dependency_mode,
            missing_dependencies=missing_dependencies,
            note=definition.note,
        )
        resolved[definition.code] = coverage
        return coverage

    factors = [resolve(definition, set()) for definition in FACTOR_REGISTRY]
    known = [factor for factor in factors if factor.current_epistemic_status != "UNKNOWN"]
    phase1 = [factor for factor in factors if factor.phase1_required]
    known_phase1 = [factor for factor in phase1 if factor.current_epistemic_status != "UNKNOWN"]
    layer_factors = [factor for factor in factors if factor.layer is not None]
    known_layer_factors = [
        factor for factor in layer_factors if factor.current_epistemic_status != "UNKNOWN"
    ]
    usable_layer_factors = [factor for factor in layer_factors if factor.usable_now]
    layer_rows: list[dict[str, Any]] = []
    for layer in range(1, 8):
        members = [factor for factor in factors if factor.layer == layer]
        active = [factor for factor in members if factor.current_epistemic_status != "UNKNOWN"]
        usable = [factor for factor in members if factor.usable_now]
        required = [factor for factor in members if factor.phase1_required]
        active_required = [
            factor for factor in required if factor.current_epistemic_status != "UNKNOWN"
        ]
        layer_rows.append(
            {
                "layer": layer,
                "factor_count": len(members),
                "known_factor_count": len(active),
                "usable_factor_count": len(usable),
                "book_coverage_pct": round(
                    len(active) / len(members) * 100 if members else 0,
                    2,
                ),
                "book_usable_coverage_pct": round(
                    len(usable) / len(members) * 100 if members else 0,
                    2,
                ),
                "phase1_required_count": len(required),
                "phase1_known_count": len(active_required),
                "phase1_coverage_pct": round(
                    len(active_required) / len(required) * 100 if required else 0,
                    2,
                ),
            }
        )
    return CoverageReport(
        as_of=as_of,
        registry_version=FACTOR_REGISTRY_VERSION,
        registry_hash=registry_hash(),
        total_factors=len(factors),
        known_factors=len(known),
        phase1_required_factors=len(phase1),
        phase1_known_factors=len(known_phase1),
        phase1_coverage_pct=round(
            len(known_phase1) / len(phase1) * 100 if phase1 else 0,
            2,
        ),
        book_layer_factors=len(layer_factors),
        book_layer_known_factors=len(known_layer_factors),
        book_layer_usable_factors=len(usable_layer_factors),
        book_factor_coverage_pct=round(
            len(known_layer_factors) / len(layer_factors) * 100
            if layer_factors
            else 0,
            2,
        ),
        book_usable_coverage_pct=round(
            len(usable_layer_factors) / len(layer_factors) * 100
            if layer_factors
            else 0,
            2,
        ),
        layers=layer_rows,
        factors=factors,
    )


def coverage_to_dict(report: CoverageReport) -> dict[str, Any]:
    return {
        **asdict(report),
        "factors": [asdict(factor) for factor in report.factors],
    }
