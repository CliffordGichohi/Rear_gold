from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.analytics.real_yield import RealYieldPoint, calculate_real_yield_impulse
from gold_intel.analytics.scoring import calculate_partial_score
from gold_intel.analytics.sessions import session_at
from gold_intel.analytics.structure import (
    MinuteBar,
    aggregate_five_minutes,
    calculate_five_minute_acceptance,
)
from gold_intel.domain.signals import SignalResult
from gold_intel.infrastructure.models import Observation, PriceBar, ScoreSnapshot, Signal

RULESET_VERSION = "vertical-slice-1"


async def calculate_intelligence(
    session: AsyncSession, *, instrument_code: str, as_of: datetime
) -> ScoreSnapshot:
    existing = await session.scalar(
        select(ScoreSnapshot).where(
            ScoreSnapshot.instrument_code == instrument_code,
            ScoreSnapshot.as_of == as_of,
            ScoreSnapshot.ruleset_version == RULESET_VERSION,
        )
    )
    if existing:
        return existing

    price_rows = list(
        (
            await session.scalars(
                select(PriceBar)
                .where(
                    PriceBar.instrument_code == instrument_code,
                    PriceBar.timeframe == "1m",
                    PriceBar.close_time <= as_of,
                    PriceBar.available_at <= as_of,
                )
                .order_by(desc(PriceBar.open_time))
                .limit(2500)
            )
        ).all()
    )
    price_rows.reverse()
    observation_rows = list(
        (
            await session.scalars(
                select(Observation)
                .where(
                    Observation.series_code == "US_REAL_YIELD_10Y",
                    Observation.available_at <= as_of,
                )
                .order_by(Observation.observation_time, Observation.available_at)
            )
        ).all()
    )

    minute_bars = [
        MinuteBar(
            id=row.id,
            open_time=row.open_time,
            close_time=row.close_time,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume) if row.volume is not None else None,
            available_at=row.available_at,
        )
        for row in price_rows
    ]
    real_yield_points = [
        RealYieldPoint(
            id=row.id,
            observation_time=row.observation_time,
            available_at=row.available_at,
            value_percent=float(row.value),
            vintage=row.vintage,
        )
        for row in observation_rows
    ]
    real_yield_signal = calculate_real_yield_impulse(real_yield_points, as_of)
    aggregates = aggregate_five_minutes(minute_bars, as_of)
    acceptance_signal = calculate_five_minute_acceptance(aggregates, as_of)
    signals = [real_yield_signal, acceptance_signal]
    session_context = session_at(as_of)
    score = calculate_partial_score(signals, session_name=session_context.primary)

    persisted_signal_ids: list[str] = []
    for result in signals:
        model = _signal_model(result)
        session.add(model)
        persisted_signal_ids.append(str(model.id))

    snapshot = ScoreSnapshot(
        id=uuid4(),
        instrument_code=instrument_code,
        as_of=as_of,
        overall_score=Decimal(str(score.overall_score)),
        bullish_score=Decimal(str(score.bullish_score)),
        bearish_score=Decimal(str(score.bearish_score)),
        neutrality_score=Decimal(str(score.neutrality_score)),
        conflict_score=Decimal(str(score.conflict_score)),
        confidence=Decimal(str(score.confidence)),
        coverage=Decimal(str(score.coverage)),
        bias_label=score.bias_label,
        execution_state=score.execution_state,
        dominant_driver=score.dominant_driver,
        main_contradiction=score.main_contradiction,
        reasoning={
            **score.reasoning,
            "contributions": score.contributions,
            "session_evidence": session_context.evidence,
        },
        layers=score.layers,
        signal_ids=persisted_signal_ids,
        ruleset_version=RULESET_VERSION,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def latest_snapshot(
    session: AsyncSession, *, instrument_code: str = "XAUUSD"
) -> ScoreSnapshot | None:
    snapshot: ScoreSnapshot | None = await session.scalar(
        select(ScoreSnapshot)
        .where(ScoreSnapshot.instrument_code == instrument_code)
        .order_by(desc(ScoreSnapshot.as_of))
        .limit(1)
    )
    return snapshot


async def snapshot_signals(session: AsyncSession, snapshot: ScoreSnapshot) -> list[Signal]:
    identifiers = [UUID(value) for value in snapshot.signal_ids]
    if not identifiers:
        return []
    return list((await session.scalars(select(Signal).where(Signal.id.in_(identifiers)))).all())


def _signal_model(result: SignalResult) -> Signal:
    return Signal(
        id=result.id,
        name=result.name,
        layer=result.layer,
        driver=result.driver,
        epistemic_status=result.epistemic_status,
        direction=Decimal(str(result.direction)),
        strength=Decimal(str(result.strength)),
        confidence=Decimal(str(result.confidence)),
        freshness=Decimal(str(result.freshness)),
        data_quality=Decimal(str(result.data_quality)),
        explanation=result.explanation,
        evidence=result.evidence,
        contradicting_evidence=result.contradicting_evidence,
        observed_at=result.observed_at,
        available_at=result.available_at,
        expires_at=result.expires_at,
        ruleset_version=result.ruleset_version,
    )
