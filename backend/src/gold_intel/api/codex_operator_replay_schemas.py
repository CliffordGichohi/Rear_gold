from __future__ import annotations

import re
from enum import StrEnum
from math import isfinite
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gold_intel.api.blind_replay_v3_schemas import ReplayV3Drawing


ALIAS_PATTERN = r"^CBR-2022-\d{3}$"
TIMEFRAME_PATTERN = r"^(1w|1d|4h|1h|15m|5m|1m)$"
UTC_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"


class CodexReplayAction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


class CodexSetupClass(StrEnum):
    MACRO_ALIGNED_CONTINUATION = "MACRO_ALIGNED_CONTINUATION"
    COUNTER_MACRO_RANGE_ROTATION = "COUNTER_MACRO_RANGE_ROTATION"
    MACRO_NEUTRAL_AUCTION_TRADE = "MACRO_NEUTRAL_AUCTION_TRADE"


class CodexAdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_alias: str = Field(pattern=ALIAS_PATTERN)
    expected_cursor_at: str = Field(pattern=UTC_PATTERN)
    increment_minutes: int
    selected_timeframe: str = Field(pattern=TIMEFRAME_PATTERN)

    @model_validator(mode="after")
    def increment_is_frozen(self) -> Self:
        if self.increment_minutes not in {1, 5, 15}:
            raise ValueError("increment_minutes must be 1, 5, or 15")
        return self


class CodexInspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_alias: str = Field(pattern=ALIAS_PATTERN)
    expected_cursor_at: str = Field(pattern=UTC_PATTERN)
    selected_timeframe: str = Field(pattern=TIMEFRAME_PATTERN)
    screenshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CodexDecisionAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setup_class: CodexSetupClass | None = None
    thesis: str = Field(min_length=3, max_length=4000)
    macro_regime: str = Field(min_length=1, max_length=500)
    macro_directional_pressure: str = Field(min_length=1, max_length=500)
    macro_role: str = Field(pattern=r"^(DIRECTION_DRIVER|CONTEXT_ONLY|NEUTRAL)$")
    macro_freshness: str = Field(min_length=1, max_length=500)
    dominant_driver: str = Field(min_length=1, max_length=500)
    catalyst_risk: str = Field(min_length=1, max_length=500)
    higher_timeframe_state: str = Field(pattern=r"^(TREND|RANGE|CONFLICTED|UNKNOWN)$")
    higher_timeframe_context: str = Field(min_length=3, max_length=2000)
    location_timeframe: str = Field(pattern=TIMEFRAME_PATTERN)
    preexisting_location: str = Field(min_length=3, max_length=2000)
    m15_transition: str = Field(min_length=3, max_length=2000)
    session_liquidity_context: str = Field(min_length=3, max_length=2000)
    invalidation_timeframe: str = Field(pattern=TIMEFRAME_PATTERN)
    invalidation_condition: str = Field(min_length=3, max_length=2000)
    target_timeframe: str = Field(pattern=TIMEFRAME_PATTERN)
    target_type: str = Field(pattern=r"^(INTERNAL_LIQUIDITY|EXTERNAL_LIQUIDITY|NOT_APPLICABLE)$")
    target_logic: str = Field(min_length=3, max_length=2000)
    macro_confidence: int = Field(ge=0, le=100)
    setup_quality: int = Field(ge=0, le=100)
    execution_quality: int = Field(ge=0, le=100)
    no_trade_reason: str | None = Field(default=None, max_length=2000)


class CodexDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_alias: str = Field(pattern=ALIAS_PATTERN)
    expected_cursor_at: str = Field(pattern=UTC_PATTERN)
    selected_timeframe: str = Field(pattern=TIMEFRAME_PATTERN)
    client_visible_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predecision_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inspected_timeframes: list[str] = Field(min_length=1, max_length=7)
    action: CodexReplayAction
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    drawings: list[ReplayV3Drawing] = Field(default_factory=list, max_length=300)
    annotation: CodexDecisionAnnotation

    @model_validator(mode="after")
    def frozen_decision_shape(self) -> Self:
        if len(set(self.inspected_timeframes)) != len(self.inspected_timeframes):
            raise ValueError("inspected_timeframes must be unique")
        if any(not re.fullmatch(TIMEFRAME_PATTERN[1:-1], value) for value in self.inspected_timeframes):
            raise ValueError("inspected_timeframes contains an unsupported timeframe")
        if self.action is CodexReplayAction.NO_TRADE:
            if any(value is not None for value in (self.entry, self.stop, self.target)) or self.drawings:
                raise ValueError("NO_TRADE cannot include execution geometry or drawings")
            if self.annotation.setup_class is not None or not self.annotation.no_trade_reason:
                raise ValueError("NO_TRADE requires a reason and no setup_class")
            return self
        values = (self.entry, self.stop, self.target)
        if any(value is None or not isfinite(float(value)) for value in values):
            raise ValueError("a trade requires finite entry, stop, and target")
        entry, stop, target = (float(value) for value in values)
        if self.action is CodexReplayAction.LONG and not stop < entry < target:
            raise ValueError("LONG requires stop < entry < target")
        if self.action is CodexReplayAction.SHORT and not target < entry < stop:
            raise ValueError("SHORT requires target < entry < stop")
        if self.annotation.setup_class is None or self.annotation.no_trade_reason:
            raise ValueError("a trade requires setup_class and no no_trade_reason")
        if (
            self.annotation.setup_class is CodexSetupClass.COUNTER_MACRO_RANGE_ROTATION
            and self.annotation.higher_timeframe_state != "RANGE"
        ):
            raise ValueError("counter-macro range rotation requires higher_timeframe_state=RANGE")
        ids = [drawing.drawing_id for drawing in self.drawings]
        if len(ids) != len(set(ids)):
            raise ValueError("drawing_id values must be unique")
        positions = [drawing for drawing in self.drawings if drawing.kind.value in {"LONG_POSITION", "SHORT_POSITION"}]
        if len(positions) != 1:
            raise ValueError("a trade requires exactly one position drawing")
        expected = "LONG_POSITION" if self.action is CodexReplayAction.LONG else "SHORT_POSITION"
        if positions[0].kind.value != expected:
            raise ValueError("position drawing direction differs")
        prices = [anchor.price for anchor in positions[0].anchors]
        if any(abs(left - right) > 1e-8 for left, right in zip(prices, (entry, stop, target), strict=True)):
            raise ValueError("position drawing geometry differs from the decision")
        return self


class CodexReplayStatusResponse(BaseModel):
    protocol: str
    ready: bool
    phase: str
    cases_completed: int
    cases_total: int
    current_case_alias: str | None
    visible_ledger_head_sha256: str
    outcome_vault_state: str
    human_decisions: str
    calendar_2025: str
    calendar_2026: str
    research_credit: str
    cases: list[dict[str, Any]]


class CodexReplaySnapshotResponse(BaseModel):
    case: dict[str, Any]
    progress: CodexReplayStatusResponse


class CodexReplayMutationResponse(BaseModel):
    event_sha256: str
    idempotent_replay: bool
    case: dict[str, Any] | None
    progress: CodexReplayStatusResponse
    outcome_hidden: bool = True
