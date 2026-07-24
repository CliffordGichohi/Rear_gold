from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

EpistemicStatus = Literal["OBSERVED", "CALCULATED", "INFERRED", "UNKNOWN"]


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


@dataclass(frozen=True, slots=True)
class SignalResult:
    name: str
    layer: int
    driver: str
    epistemic_status: EpistemicStatus
    direction: float
    strength: float
    confidence: float
    freshness: float
    data_quality: float
    explanation: str
    observed_at: datetime
    available_at: datetime
    evidence: dict[str, Any] = field(default_factory=dict)
    contradicting_evidence: dict[str, Any] = field(default_factory=dict)
    expires_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    ruleset_version: str = "vertical-slice-1"

    def __post_init__(self) -> None:
        if not -1 <= self.direction <= 1:
            raise ValueError("direction must be between -1 and 1")
        for field_name in ("strength", "confidence", "freshness", "data_quality"):
            value = getattr(self, field_name)
            if not 0 <= value <= 100:
                raise ValueError(f"{field_name} must be between 0 and 100")
        if not 1 <= self.layer <= 7:
            raise ValueError("layer must be between 1 and 7")

    @property
    def certainty(self) -> float:
        return (self.confidence / 100) * (self.freshness / 100) * (self.data_quality / 100)


@dataclass(frozen=True, slots=True)
class ScoreResult:
    overall_score: float
    bullish_score: float
    bearish_score: float
    neutrality_score: float
    conflict_score: float
    confidence: float
    coverage: float
    bias_label: str
    execution_state: str
    dominant_driver: str | None
    main_contradiction: str | None
    contributions: list[dict[str, Any]]
    layers: list[dict[str, Any]]
    reasoning: dict[str, Any]
