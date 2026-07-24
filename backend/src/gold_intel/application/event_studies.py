from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.analytics.event_studies import (
    EVENT_REACTION_VERSION,
    ReactionBar,
    ReactionResult,
    calculate_event_reactions,
    summarize_event_reactions,
)
from gold_intel.analytics.events import SurpriseCalculation
from gold_intel.infrastructure.models import (
    EconomicEvent,
    EconomicRelease,
    EconomicSurprise,
    EventReaction,
    EventStudyRun,
    PriceBar,
)


async def execute_event_study(
    session: AsyncSession,
    *,
    instrument: str,
    provider_code: str,
    start: datetime,
    end: datetime,
    study_as_of: datetime,
    data_mode: str,
    minimum_importance: int,
    component_codes: list[str],
) -> EventStudyRun:
    _validate_request(
        start=start,
        end=end,
        study_as_of=study_as_of,
        data_mode=data_mode,
    )
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    cutoff = study_as_of.astimezone(UTC)
    synthetic = data_mode == "SYNTHETIC_ONLY"

    candidate_query = (
        select(EconomicEvent, EconomicRelease)
        .join(EconomicRelease, EconomicRelease.event_id == EconomicEvent.id)
        .where(
            EconomicRelease.released_at >= start_utc,
            EconomicRelease.released_at < end_utc,
            EconomicRelease.available_at <= cutoff,
            EconomicRelease.is_revision.is_(False),
            EconomicEvent.importance >= minimum_importance,
            EconomicEvent.is_synthetic.is_(synthetic),
            EconomicRelease.is_synthetic.is_(synthetic),
        )
        .order_by(EconomicRelease.released_at)
    )
    if component_codes:
        candidate_query = candidate_query.where(EconomicRelease.component_code.in_(component_codes))
    candidates = list((await session.execute(candidate_query)).all())
    release_ids = [release.id for _, release in candidates]

    surprise_rows = (
        list(
            (
                await session.scalars(
                    select(EconomicSurprise)
                    .where(
                        EconomicSurprise.release_id.in_(release_ids),
                        EconomicSurprise.available_at <= cutoff,
                        EconomicSurprise.is_synthetic.is_(synthetic),
                    )
                    .order_by(
                        EconomicSurprise.released_at,
                        EconomicSurprise.history_count.desc(),
                        EconomicSurprise.created_at.desc(),
                    )
                )
            ).all()
        )
        if release_ids
        else []
    )
    surprise_by_release: dict[Any, EconomicSurprise] = {}
    for surprise_row in surprise_rows:
        surprise_by_release.setdefault(
            surprise_row.release_id,
            surprise_row,
        )

    price_end = min(cutoff, end_utc + timedelta(days=2))
    price_rows = list(
        (
            await session.scalars(
                select(PriceBar)
                .where(
                    PriceBar.instrument_code == instrument,
                    PriceBar.provider_code == provider_code,
                    PriceBar.timeframe == "1m",
                    PriceBar.open_time >= start_utc - timedelta(minutes=10),
                    PriceBar.open_time < price_end,
                    PriceBar.available_at <= cutoff,
                    PriceBar.is_complete.is_(True),
                    PriceBar.is_synthetic.is_(synthetic),
                )
                .order_by(PriceBar.open_time, PriceBar.available_at)
            )
        ).all()
    )
    bars = [
        ReactionBar(
            open_time=row.open_time,
            close_time=row.close_time,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            available_at=row.available_at,
            source_record_key=row.source_record_key,
            is_synthetic=row.is_synthetic,
        )
        for row in price_rows
    ]

    reactions: list[ReactionResult] = []
    exclusions: list[dict[str, Any]] = []
    eligible_releases = 0
    for event, release in candidates:
        surprise_model = surprise_by_release.get(release.id)
        if surprise_model is None:
            exclusions.append(
                {
                    "event_id": str(event.id),
                    "release_id": str(release.id),
                    "event_code": event.event_code,
                    "component_code": release.component_code,
                    "released_at": release.released_at.isoformat(),
                    "reason": "NO_ELIGIBLE_POINT_IN_TIME_SURPRISE",
                }
            )
            continue
        surprise_calculation = _surprise_calculation(surprise_model, event)
        reaction_batch = calculate_event_reactions(
            surprise_calculation,
            bars,
            study_as_of=cutoff,
            surprise_id=surprise_model.id,
        )
        if not reaction_batch.reactions:
            exclusions.append(
                {
                    "event_id": str(event.id),
                    "release_id": str(release.id),
                    "event_code": event.event_code,
                    "component_code": release.component_code,
                    "released_at": release.released_at.isoformat(),
                    "reason": reaction_batch.exclusion,
                }
            )
            continue
        eligible_releases += 1
        for reaction in reaction_batch.reactions:
            await _persist_reaction(
                session,
                reaction=reaction,
                instrument=instrument,
                provider_code=provider_code,
            )
            reactions.append(reaction)

    summary = summarize_event_reactions(reactions)
    result_payload = {
        **summary,
        "reaction_count": len(reactions),
        "reactions": [_reaction_dict(reaction) for reaction in reactions],
        "interpretation": (
            "Returns describe observed post-release gold paths. Direction alignment "
            "compares those paths with the configured macro template; it is not a "
            "causal claim or a trading signal."
        ),
    }
    exclusion_payload = {
        "count": len(exclusions),
        "by_reason": _exclusion_counts(exclusions),
        "details": exclusions,
    }
    parameters = {
        "study_as_of": cutoff.isoformat(),
        "data_mode": data_mode,
        "minimum_importance": minimum_importance,
        "component_codes": component_codes,
        "horizons": ["1M", "5M", "15M", "1H", "4H", "DAILY_CLOSE"],
        "reaction_version": EVENT_REACTION_VERSION,
        "price_policy": (
            "Earliest complete 1m version available by study_as_of; reference is "
            "the last complete close at or before release."
        ),
    }
    data_hash = _run_hash(
        instrument=instrument,
        provider_code=provider_code,
        start=start_utc,
        end=end_utc,
        parameters=parameters,
        reactions=reactions,
        exclusions=exclusions,
    )
    now = datetime.now(UTC)
    run = EventStudyRun(
        id=uuid4(),
        instrument_code=instrument,
        provider_code=provider_code,
        start_time=start_utc,
        end_time=end_utc,
        status=("COMPLETED" if eligible_releases else "COMPLETED_NO_DATA"),
        parameters=parameters,
        data_hash=data_hash,
        candidate_count=len(candidates),
        eligible_count=eligible_releases,
        exclusions=exclusion_payload,
        results=result_payload,
        completed_at=now,
    )
    session.add(run)
    await session.flush()
    return run


def event_study_to_dict(run: EventStudyRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "instrument": run.instrument_code,
        "provider_code": run.provider_code,
        "start": run.start_time,
        "end": run.end_time,
        "status": run.status,
        "parameters": run.parameters,
        "data_hash": run.data_hash,
        "candidate_count": run.candidate_count,
        "eligible_count": run.eligible_count,
        "exclusions": run.exclusions,
        "results": run.results,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }


async def _persist_reaction(
    session: AsyncSession,
    *,
    reaction: ReactionResult,
    instrument: str,
    provider_code: str,
) -> EventReaction:
    existing = await session.scalar(
        select(EventReaction).where(
            EventReaction.release_id == reaction.release_id,
            EventReaction.instrument_code == instrument,
            EventReaction.provider_code == provider_code,
            EventReaction.horizon_code == reaction.horizon_code,
            EventReaction.calculation_version == EVENT_REACTION_VERSION,
            EventReaction.data_hash == reaction.data_hash,
        )
    )
    if existing is not None:
        return existing
    model = EventReaction(
        id=uuid4(),
        event_id=reaction.event_id,
        release_id=reaction.release_id,
        surprise_id=reaction.surprise_id,
        instrument_code=instrument,
        provider_code=provider_code,
        horizon_code=reaction.horizon_code,
        reference_time=reaction.reference_time,
        reference_price=_decimal(reaction.reference_price),
        horizon_time=reaction.horizon_time,
        horizon_price=_decimal(reaction.horizon_price),
        price_change=_decimal(reaction.price_change),
        return_pct=_decimal(reaction.return_pct),
        mfe_price=_decimal(reaction.mfe_price),
        mae_price=_decimal(reaction.mae_price),
        first_move_direction=reaction.first_move_direction,
        first_move_held=reaction.first_move_held,
        available_at=reaction.available_at,
        calculation_version=EVENT_REACTION_VERSION,
        data_hash=reaction.data_hash,
        evidence=reaction.evidence,
        is_synthetic=reaction.is_synthetic,
    )
    session.add(model)
    return model


def _surprise_calculation(
    model: EconomicSurprise,
    event: EconomicEvent,
) -> SurpriseCalculation:
    evidence = model.evidence
    return SurpriseCalculation(
        event_id=model.event_id,
        release_id=model.release_id,
        forecast_id=model.forecast_id,
        event_code=event.event_code,
        event_name=event.name,
        component_code=model.component_code,
        released_at=model.released_at,
        available_at=model.available_at,
        actual_value=float(evidence["actual"]),
        forecast_value=float(evidence["forecast"]),
        previous_value=_optional_float(evidence.get("previous")),
        revised_previous_value=_optional_float(evidence.get("revised_previous")),
        unit=str(evidence["unit"]),
        raw_surprise=float(model.raw_surprise),
        standardized_surprise=float(model.standardized_surprise),
        gold_direction=float(model.gold_direction),
        strength=float(model.strength),
        confidence=float(model.confidence),
        history_count=model.history_count,
        method=model.method,
        epistemic_status=model.epistemic_status,
        explanation=model.explanation,
        evidence=evidence,
        data_hash=model.data_hash,
        is_synthetic=model.is_synthetic,
    )


def _reaction_dict(reaction: ReactionResult) -> dict[str, Any]:
    return {
        **asdict(reaction),
        "event_id": str(reaction.event_id),
        "release_id": str(reaction.release_id),
        "surprise_id": (str(reaction.surprise_id) if reaction.surprise_id is not None else None),
        "reference_time": reaction.reference_time.isoformat(),
        "horizon_time": reaction.horizon_time.isoformat(),
        "available_at": reaction.available_at.isoformat(),
    }


def _exclusion_counts(
    exclusions: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for exclusion in exclusions:
        reason = str(exclusion["reason"])
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _run_hash(
    *,
    instrument: str,
    provider_code: str,
    start: datetime,
    end: datetime,
    parameters: dict[str, Any],
    reactions: list[ReactionResult],
    exclusions: list[dict[str, Any]],
) -> str:
    payload = {
        "instrument": instrument,
        "provider_code": provider_code,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "parameters": parameters,
        "reaction_hashes": [reaction.data_hash for reaction in reactions],
        "exclusions": exclusions,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_request(
    *,
    start: datetime,
    end: datetime,
    study_as_of: datetime,
    data_mode: str,
) -> None:
    if any(value.tzinfo is None for value in (start, end, study_as_of)):
        raise ValueError("start, end, and study_as_of must include a timezone")
    if start >= end:
        raise ValueError("start must precede end")
    if study_as_of < end:
        raise ValueError("study_as_of cannot precede end")
    if data_mode not in {"REAL_ONLY", "SYNTHETIC_ONLY"}:
        raise ValueError("data_mode must be REAL_ONLY or SYNTHETIC_ONLY")


def _optional_float(value: Any | None) -> float | None:
    return None if value is None else float(value)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))
