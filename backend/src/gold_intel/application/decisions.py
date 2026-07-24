from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.analytics.decision import (
    DECISION_RULESET_VERSION,
    SevenLayerDecision,
    calculate_seven_layer_decision,
)
from gold_intel.application.factor_coverage import (
    build_coverage_report,
    coverage_to_dict,
)
from gold_intel.application.fundamentals import (
    calculate_and_store_fundamental_snapshot,
)
from gold_intel.application.market_structure import (
    StructureDataMode,
    calculate_market_structure,
)
from gold_intel.infrastructure.models import DecisionSnapshot


async def calculate_and_store_decision(
    session: AsyncSession,
    *,
    instrument: str,
    provider_code: str | None,
    as_of: datetime,
    data_mode: StructureDataMode = "AUTO",
    max_source_bars: int = 60_000,
) -> tuple[DecisionSnapshot, SevenLayerDecision, bool]:
    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    cutoff = as_of.astimezone(UTC)
    fundamental_snapshot, fundamental_state, _ = (
        await calculate_and_store_fundamental_snapshot(
            session,
            instrument=instrument,
            as_of=cutoff,
        )
    )
    structure = await calculate_market_structure(
        session,
        instrument=instrument,
        provider_code=provider_code,
        as_of=cutoff,
        data_mode=data_mode,
        chart_timeframe="5m",
        max_source_bars=max_source_bars,
    )
    coverage = await build_coverage_report(session, as_of=cutoff)
    decision = calculate_seven_layer_decision(
        fundamental_state,
        structure=structure,
        coverage=coverage_to_dict(coverage),
    )
    existing = await session.scalar(
        select(DecisionSnapshot).where(
            DecisionSnapshot.instrument_code == instrument,
            DecisionSnapshot.as_of == decision.as_of,
            DecisionSnapshot.ruleset_version == DECISION_RULESET_VERSION,
            DecisionSnapshot.data_hash == decision.data_hash,
        )
    )
    if existing is not None:
        return existing, decision, False

    model = DecisionSnapshot(
        instrument_code=instrument,
        provider_code=(
            str(structure["provider_code"])
            if structure is not None
            else provider_code
        ),
        as_of=decision.as_of,
        epistemic_status=decision.epistemic_status,
        directional_score=_decimal(decision.directional_score),
        bullish_score=_decimal(decision.bullish_score),
        bearish_score=_decimal(decision.bearish_score),
        neutral_conflict_score=_decimal(decision.neutral_conflict_score),
        directional_confidence=_decimal(decision.directional_confidence),
        execution_confidence=_decimal(decision.execution_confidence),
        directional_evidence_coverage_pct=_decimal(
            decision.directional_evidence_coverage_pct
        ),
        phase1_factor_coverage_pct=_decimal(decision.phase1_factor_coverage_pct),
        book_factor_coverage_pct=_decimal(decision.book_factor_coverage_pct),
        book_usable_coverage_pct=_decimal(decision.book_usable_coverage_pct),
        bias_label=decision.bias,
        regime_label=decision.regime,
        reaction_function=decision.reaction_function,
        dominant_driver=decision.dominant_driver,
        main_contradiction=decision.main_contradiction,
        highest_risk_assumption=decision.highest_risk_assumption,
        upcoming_catalyst=decision.upcoming_catalyst,
        event_risk=decision.event_risk,
        current_session=decision.current_session,
        liquidity_state=decision.liquidity_state,
        price_macro_alignment=decision.price_macro_alignment,
        execution_state=decision.execution_state,
        layers=[asdict(layer) for layer in decision.layers],
        components=[asdict(component) for component in decision.components],
        execution_plan=decision.execution_plan,
        reasoning=decision.reasoning,
        fundamental_snapshot_id=fundamental_snapshot.id,
        fundamental_data_hash=decision.fundamental_data_hash,
        structure_data_hash=decision.structure_data_hash,
        registry_hash=decision.registry_hash,
        data_hash=decision.data_hash,
        ruleset_version=decision.ruleset_version,
    )
    session.add(model)
    await session.flush()
    return model, decision, True


def decision_snapshot_to_dict(snapshot: DecisionSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "instrument": snapshot.instrument_code,
        "provider_code": snapshot.provider_code,
        "as_of": snapshot.as_of,
        "epistemic_status": snapshot.epistemic_status,
        "directional_score": float(snapshot.directional_score),
        "bullish_score": float(snapshot.bullish_score),
        "bearish_score": float(snapshot.bearish_score),
        "neutral_conflict_score": float(snapshot.neutral_conflict_score),
        "directional_confidence": float(snapshot.directional_confidence),
        "execution_confidence": float(snapshot.execution_confidence),
        "directional_evidence_coverage_pct": float(
            snapshot.directional_evidence_coverage_pct
        ),
        "phase1_factor_coverage_pct": float(snapshot.phase1_factor_coverage_pct),
        "book_factor_coverage_pct": float(snapshot.book_factor_coverage_pct),
        "book_usable_coverage_pct": float(snapshot.book_usable_coverage_pct),
        "bias": snapshot.bias_label,
        "regime": snapshot.regime_label,
        "reaction_function": snapshot.reaction_function,
        "dominant_driver": snapshot.dominant_driver,
        "main_contradiction": snapshot.main_contradiction,
        "highest_risk_assumption": snapshot.highest_risk_assumption,
        "upcoming_catalyst": snapshot.upcoming_catalyst,
        "event_risk": snapshot.event_risk,
        "current_session": snapshot.current_session,
        "liquidity_state": snapshot.liquidity_state,
        "price_macro_alignment": snapshot.price_macro_alignment,
        "execution_state": snapshot.execution_state,
        "layers": snapshot.layers,
        "components": snapshot.components,
        "execution_plan": snapshot.execution_plan,
        "reasoning": snapshot.reasoning,
        "fundamental_snapshot_id": snapshot.fundamental_snapshot_id,
        "fundamental_data_hash": snapshot.fundamental_data_hash,
        "structure_data_hash": snapshot.structure_data_hash,
        "registry_hash": snapshot.registry_hash,
        "data_hash": snapshot.data_hash,
        "ruleset_version": snapshot.ruleset_version,
        "created_at": snapshot.created_at,
    }


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))
