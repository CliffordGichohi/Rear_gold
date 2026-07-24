from __future__ import annotations

from gold_intel.api.schemas import IntelligenceSnapshotResponse, SignalResponse
from gold_intel.infrastructure.models import ScoreSnapshot, Signal


def serialize_snapshot(snapshot: ScoreSnapshot) -> IntelligenceSnapshotResponse:
    return IntelligenceSnapshotResponse(
        id=snapshot.id,
        instrument=snapshot.instrument_code,
        as_of=snapshot.as_of,
        overall_score=float(snapshot.overall_score),
        bullish_score=float(snapshot.bullish_score),
        bearish_score=float(snapshot.bearish_score),
        neutrality_score=float(snapshot.neutrality_score),
        conflict_score=float(snapshot.conflict_score),
        confidence=float(snapshot.confidence),
        evidence_coverage=float(snapshot.coverage),
        bias=snapshot.bias_label,
        execution_state=snapshot.execution_state,
        dominant_driver=snapshot.dominant_driver,
        main_contradiction=snapshot.main_contradiction,
        ruleset_version=snapshot.ruleset_version,
        reasoning=snapshot.reasoning,
        layers=snapshot.layers,
        signal_ids=snapshot.signal_ids,
    )


def serialize_signal(signal: Signal) -> SignalResponse:
    return SignalResponse(
        id=signal.id,
        name=signal.name,
        layer=signal.layer,
        driver=signal.driver,
        epistemic_status=signal.epistemic_status,
        direction=float(signal.direction),
        strength=float(signal.strength),
        confidence=float(signal.confidence),
        freshness=float(signal.freshness),
        data_quality=float(signal.data_quality),
        explanation=signal.explanation,
        observed_at=signal.observed_at,
        available_at=signal.available_at,
        expires_at=signal.expires_at,
        evidence=signal.evidence,
    )
