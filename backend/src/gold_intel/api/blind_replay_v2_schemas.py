from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReplayV2Action(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


class ReplayV2EntryTrigger(StrEnum):
    MARKET = "MARKET"
    PULLBACK_LIMIT = "PULLBACK_LIMIT"
    BREAKOUT_STOP = "BREAKOUT_STOP"


class ReplayV2EvidenceCode(StrEnum):
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


class ReplayV2DrawingKind(StrEnum):
    TREND_LINE = "TREND_LINE"
    HORIZONTAL_LINE = "HORIZONTAL_LINE"
    FIBONACCI = "FIBONACCI"
    RULER = "RULER"
    LONG_POSITION = "LONG_POSITION"
    SHORT_POSITION = "SHORT_POSITION"


class ReplayV2Anchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relative_minute: int = Field(le=180)
    price_index: float
    source_timeframe: str = Field(pattern=r"^(1w|1d|4h|1h|15m|5m|1m)$")

    @model_validator(mode="after")
    def finite_price(self) -> Self:
        if not isfinite(self.price_index):
            raise ValueError("price_index must be finite")
        return self


class ReplayV2Drawing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawing_id: str = Field(min_length=1, max_length=128)
    kind: ReplayV2DrawingKind
    anchors: list[ReplayV2Anchor] = Field(min_length=1, max_length=3)
    placed_at_cursor_minute: int = Field(ge=0, le=180)

    @model_validator(mode="after")
    def exact_anchor_count(self) -> Self:
        expected = {
            ReplayV2DrawingKind.HORIZONTAL_LINE: 1,
            ReplayV2DrawingKind.TREND_LINE: 2,
            ReplayV2DrawingKind.FIBONACCI: 2,
            ReplayV2DrawingKind.RULER: 2,
            ReplayV2DrawingKind.LONG_POSITION: 3,
            ReplayV2DrawingKind.SHORT_POSITION: 3,
        }[self.kind]
        if len(self.anchors) != expected:
            raise ValueError(f"{self.kind.value} requires exactly {expected} anchor(s)")
        return self


class BlindReplayV2AdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_alias: str = Field(pattern=r"^P-\d{3}$")
    expected_cursor_minute: int = Field(ge=0, le=179)
    increment_minutes: int
    selected_timeframe: str = Field(pattern=r"^(1w|1d|4h|1h|15m|5m|1m)$")

    @model_validator(mode="after")
    def permitted_increment(self) -> Self:
        if self.increment_minutes not in {1, 5, 15}:
            raise ValueError("increment_minutes must be 1, 5, or 15")
        if self.expected_cursor_minute + self.increment_minutes > 180:
            raise ValueError("cursor increment exceeds the frozen minute-180 boundary")
        return self


class BlindReplayV2DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_alias: str = Field(pattern=r"^P-\d{3}$")
    expected_cursor_minute: int = Field(ge=0, le=180)
    selected_timeframe: str = Field(pattern=r"^(1w|1d|4h|1h|15m|5m|1m)$")
    client_visible_charts_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: ReplayV2Action
    confidence: int = Field(ge=50, le=100)
    entry_trigger: ReplayV2EntryTrigger | None = None
    entry_index: float | None = None
    stop_index: float | None = None
    target_index: float | None = None
    drawings: list[ReplayV2Drawing] = Field(default_factory=list, max_length=200)
    evidence_codes: list[ReplayV2EvidenceCode] = Field(min_length=1, max_length=10)
    trade_reason: str = Field(min_length=3, max_length=2000)
    trigger_condition: str = Field(min_length=3, max_length=1000)
    invalidation: str = Field(min_length=3, max_length=1000)
    target_explanation: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if len(set(self.evidence_codes)) != len(self.evidence_codes):
            raise ValueError("evidence_codes must be unique")
        drawing_ids = [drawing.drawing_id for drawing in self.drawings]
        if len(set(drawing_ids)) != len(drawing_ids):
            raise ValueError("drawing_id values must be unique")
        positions = [
            drawing
            for drawing in self.drawings
            if drawing.kind in {ReplayV2DrawingKind.LONG_POSITION, ReplayV2DrawingKind.SHORT_POSITION}
        ]
        geometry = (self.entry_index, self.stop_index, self.target_index)
        if self.action is ReplayV2Action.NO_TRADE:
            if self.entry_trigger is not None or any(value is not None for value in geometry):
                raise ValueError("NO_TRADE requires null execution geometry")
            if positions:
                raise ValueError("NO_TRADE cannot include a position drawing")
            return self
        if self.entry_trigger is None or any(value is None for value in geometry):
            raise ValueError("A directional decision requires trigger, entry, stop, and target")
        if len(positions) != 1:
            raise ValueError("A directional decision requires exactly one position drawing")
        expected_kind = (
            ReplayV2DrawingKind.LONG_POSITION
            if self.action is ReplayV2Action.LONG
            else ReplayV2DrawingKind.SHORT_POSITION
        )
        if positions[0].kind is not expected_kind:
            raise ValueError("Position drawing direction differs from decision action")
        assert self.entry_index is not None
        assert self.stop_index is not None
        assert self.target_index is not None
        if not all(isfinite(value) for value in geometry if value is not None):
            raise ValueError("execution prices must be finite")
        if self.action is ReplayV2Action.LONG and not (
            self.stop_index < self.entry_index < self.target_index
        ):
            raise ValueError("LONG requires stop < entry < target")
        if self.action is ReplayV2Action.SHORT and not (
            self.target_index < self.entry_index < self.stop_index
        ):
            raise ValueError("SHORT requires target < entry < stop")
        anchor_prices = [anchor.price_index for anchor in positions[0].anchors]
        if any(abs(left - right) > 1e-8 for left, right in zip(anchor_prices, geometry, strict=True)):
            raise ValueError("Position drawing anchors differ from submitted entry/stop/target")
        return self


class BlindReplayV2StatusResponse(BaseModel):
    protocol: str
    ready: bool
    phase: str
    practice_completed: int
    practice_total: int
    total_locked: int
    next_case_alias: str | None
    cursor_minute: int | None
    cursor_ledger_head_sha256: str
    setup_ledger_head_sha256: str
    scored_labeling: str
    research_credit: str


class BlindReplayV2SnapshotResponse(BaseModel):
    case: dict[str, Any]
    progress: BlindReplayV2StatusResponse


class BlindReplayV2DecisionResponse(BaseModel):
    locked: bool
    idempotent_replay: bool
    record_sha256: str
    case_alias: str
    locked_cursor_minute: int
    progress: BlindReplayV2StatusResponse
    practice_feedback: dict[str, Any]
