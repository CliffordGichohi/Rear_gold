from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReplayAction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


class ReplayEntryTrigger(StrEnum):
    MARKET = "MARKET"
    PULLBACK_LIMIT = "PULLBACK_LIMIT"
    BREAKOUT_STOP = "BREAKOUT_STOP"


class ReplayEvidenceCode(StrEnum):
    FUNDAMENTAL_ALIGNMENT = "FUNDAMENTAL_ALIGNMENT"
    HTF_TREND = "HTF_TREND"
    SUPPORT_RESISTANCE = "SUPPORT_RESISTANCE"
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
    ACCEPTANCE_REJECTION = "ACCEPTANCE_REJECTION"
    BREAK_RETEST = "BREAK_RETEST"
    SESSION_RANGE = "SESSION_RANGE"
    CROSS_MARKET_CONFIRMATION = "CROSS_MARKET_CONFIRMATION"
    POSITIONING = "POSITIONING"
    OTHER = "OTHER"


class BlindReplayDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_alias: str = Field(pattern=r"^[PS]-\d{3}$")
    action: ReplayAction
    confidence: int = Field(ge=50, le=100)
    entry_trigger: ReplayEntryTrigger | None = None
    entry_offset_atr: float | None = Field(default=None, ge=-2.0, le=2.0)
    stop_distance_atr: float | None = Field(default=None, ge=0.25, le=3.0)
    target_r: float | None = Field(default=None, ge=0.5, le=5.0)
    evidence_codes: list[ReplayEvidenceCode] = Field(min_length=1, max_length=10)
    thesis: str = Field(min_length=3, max_length=1000)
    trigger_condition: str = Field(min_length=3, max_length=1000)
    invalidation: str = Field(min_length=3, max_length=1000)
    target_explanation: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def validate_frozen_geometry(self) -> Self:
        if len(set(self.evidence_codes)) != len(self.evidence_codes):
            raise ValueError("evidence_codes must be unique")
        execution = (
            self.entry_trigger,
            self.entry_offset_atr,
            self.stop_distance_atr,
            self.target_r,
        )
        if self.action is ReplayAction.NO_TRADE:
            if any(value is not None for value in execution):
                raise ValueError("NO_TRADE requires all execution fields to be null")
            return self
        if any(value is None for value in execution):
            raise ValueError("A directional decision requires every execution field")
        assert self.entry_trigger is not None
        assert self.entry_offset_atr is not None
        if self.entry_trigger is ReplayEntryTrigger.MARKET:
            if self.entry_offset_atr != 0:
                raise ValueError("MARKET requires entry_offset_atr = 0")
        elif self.action is ReplayAction.LONG:
            if self.entry_trigger is ReplayEntryTrigger.PULLBACK_LIMIT and not -2 <= self.entry_offset_atr <= 0:
                raise ValueError("LONG PULLBACK_LIMIT offset must be from -2 through 0 ATR")
            if self.entry_trigger is ReplayEntryTrigger.BREAKOUT_STOP and not 0 <= self.entry_offset_atr <= 2:
                raise ValueError("LONG BREAKOUT_STOP offset must be from 0 through 2 ATR")
        elif self.action is ReplayAction.SHORT:
            if self.entry_trigger is ReplayEntryTrigger.PULLBACK_LIMIT and not 0 <= self.entry_offset_atr <= 2:
                raise ValueError("SHORT PULLBACK_LIMIT offset must be from 0 through 2 ATR")
            if self.entry_trigger is ReplayEntryTrigger.BREAKOUT_STOP and not -2 <= self.entry_offset_atr <= 0:
                raise ValueError("SHORT BREAKOUT_STOP offset must be from -2 through 0 ATR")
        return self


class BlindReplayStatusResponse(BaseModel):
    protocol: str
    ready: bool
    phase: str
    practice_completed: int
    practice_total: int
    scored_completed: int
    scored_total: int
    total_locked: int
    next_case_alias: str | None
    ledger_head_sha256: str
    scored_outcomes_locked: bool
    research_status: str


class BlindReplayCaseResponse(BaseModel):
    case: dict[str, Any]
    progress: BlindReplayStatusResponse


class BlindReplayDecisionResponse(BaseModel):
    locked: bool
    idempotent_replay: bool
    record_sha256: str
    case_alias: str
    mode: str
    progress: BlindReplayStatusResponse
    practice_feedback: dict[str, Any] | None = None

