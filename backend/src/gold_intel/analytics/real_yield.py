from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from gold_intel.domain.signals import SignalResult, clamp

FULL_STRENGTH_BP = 20.0
FRESHNESS_HALF_LIFE_DAYS = 3.0
HARD_STALE_DAYS = 10.0


@dataclass(frozen=True, slots=True)
class RealYieldPoint:
    id: UUID
    observation_time: datetime
    available_at: datetime
    value_percent: float
    vintage: str


def calculate_real_yield_impulse(points: list[RealYieldPoint], as_of: datetime) -> SignalResult:
    eligible = [point for point in points if point.available_at <= as_of]
    latest_by_period: dict[datetime, RealYieldPoint] = {}
    for point in sorted(eligible, key=lambda item: (item.observation_time, item.available_at)):
        latest_by_period[point.observation_time] = point
    ordered = sorted(latest_by_period.values(), key=lambda item: item.observation_time)

    if len(ordered) < 6:
        return _unknown(as_of, "At least six eligible daily real-yield observations are required.")

    latest = ordered[-1]
    prior = ordered[-6]
    age_days = max(0.0, (as_of - latest.available_at).total_seconds() / 86_400)
    if age_days > HARD_STALE_DAYS:
        return _unknown(
            as_of,
            f"Latest real-yield observation is stale by {age_days:.1f} days.",
            observed_at=latest.observation_time,
            available_at=latest.available_at,
            evidence={"latest_observation_id": str(latest.id), "age_days": round(age_days, 3)},
        )

    delta_bp = (latest.value_percent - prior.value_percent) * 100
    direction = clamp(-delta_bp / FULL_STRENGTH_BP, -1, 1)
    strength = min(100.0, abs(delta_bp) / FULL_STRENGTH_BP * 100)
    freshness = 100 * (0.5 ** (age_days / FRESHNESS_HALF_LIFE_DAYS))
    stance = "support" if direction > 0 else "pressure" if direction < 0 else "neutral"

    return SignalResult(
        name="REAL_YIELD_5D_IMPULSE_V1",
        layer=6,
        driver="REAL_YIELD",
        epistemic_status="CALCULATED",
        direction=round(direction, 6),
        strength=round(strength, 3),
        confidence=95.0,
        freshness=round(freshness, 3),
        data_quality=100.0,
        explanation=(
            f"The 10-year real yield changed {delta_bp:+.1f} bp across five prior "
            f"business observations, which is calculated as {stance} for gold."
        ),
        observed_at=latest.observation_time,
        available_at=latest.available_at,
        expires_at=latest.available_at + timedelta(days=HARD_STALE_DAYS),
        evidence={
            "latest_observation_id": str(latest.id),
            "prior_observation_id": str(prior.id),
            "latest_percent": latest.value_percent,
            "prior_percent": prior.value_percent,
            "delta_bp": round(delta_bp, 4),
            "full_strength_bp": FULL_STRENGTH_BP,
            "formula": "direction=clamp(-delta_bp/20); strength=min(100,abs(delta_bp)/20*100)",
        },
    )


def _unknown(
    as_of: datetime,
    explanation: str,
    *,
    observed_at: datetime | None = None,
    available_at: datetime | None = None,
    evidence: dict[str, object] | None = None,
) -> SignalResult:
    return SignalResult(
        name="REAL_YIELD_5D_IMPULSE_V1",
        layer=6,
        driver="REAL_YIELD",
        epistemic_status="UNKNOWN",
        direction=0,
        strength=0,
        confidence=0,
        freshness=0,
        data_quality=0,
        explanation=explanation,
        observed_at=observed_at or as_of,
        available_at=available_at or as_of,
        evidence=dict(evidence or {}),
    )
