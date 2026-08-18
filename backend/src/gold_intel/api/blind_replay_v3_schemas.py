from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

TIMEFRAME_PATTERN = r"^(1w|1d|4h|1h|15m|5m|1m)$"
UTC_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"


class ReplayV3Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class ReplayV3OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class ReplayV3DrawingKind(StrEnum):
    TREND_LINE = "TREND_LINE"
    HORIZONTAL_LINE = "HORIZONTAL_LINE"
    FIBONACCI = "FIBONACCI"
    RULER = "RULER"
    LONG_POSITION = "LONG_POSITION"
    SHORT_POSITION = "SHORT_POSITION"


class ReplayV3DrawingAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_at: str = Field(pattern=UTC_PATTERN)
    price: float
    source_timeframe: str = Field(pattern=TIMEFRAME_PATTERN)

    @model_validator(mode="after")
    def finite(self) -> Self:
        if not isfinite(self.price):
            raise ValueError("drawing anchor price must be finite")
        return self


class ReplayV3Drawing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawing_id: str = Field(min_length=1, max_length=128)
    kind: ReplayV3DrawingKind
    anchors: list[ReplayV3DrawingAnchor] = Field(min_length=1, max_length=3)
    created_at_cursor: str = Field(pattern=UTC_PATTERN)

    @model_validator(mode="after")
    def exact_anchor_count(self) -> Self:
        required = {
            ReplayV3DrawingKind.HORIZONTAL_LINE: 1,
            ReplayV3DrawingKind.TREND_LINE: 2,
            ReplayV3DrawingKind.FIBONACCI: 2,
            ReplayV3DrawingKind.RULER: 2,
            ReplayV3DrawingKind.LONG_POSITION: 3,
            ReplayV3DrawingKind.SHORT_POSITION: 3,
        }[self.kind]
        if len(self.anchors) != required:
            raise ValueError(f"{self.kind.value} requires exactly {required} anchor(s)")
        return self


class ReplayV3Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thesis: str = Field(min_length=3, max_length=4000)
    fundamental_direction: str = Field(min_length=1, max_length=80)
    dominant_driver: str = Field(min_length=1, max_length=500)
    higher_timeframe_context: str = Field(min_length=3, max_length=2000)
    session_liquidity_context: str = Field(min_length=3, max_length=2000)
    entry_trigger: str = Field(min_length=3, max_length=2000)
    invalidation_logic: str = Field(min_length=3, max_length=2000)
    target_logic: str = Field(min_length=3, max_length=2000)
    event_risk: str = Field(min_length=1, max_length=500)
    confidence: int = Field(ge=0, le=100)


class ReplayV3AdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_alias: str = Field(pattern=r"^V3-P-\d{3}$")
    expected_cursor_at: str = Field(pattern=UTC_PATTERN)
    increment_minutes: int
    selected_timeframe: str = Field(pattern=TIMEFRAME_PATTERN)

    @model_validator(mode="after")
    def valid_increment(self) -> Self:
        if self.increment_minutes not in {1, 5, 15}:
            raise ValueError("increment_minutes must be 1, 5, or 15")
        return self


class ReplayV3SkipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_alias: str = Field(pattern=r"^V3-P-\d{3}$")
    expected_cursor_at: str = Field(pattern=UTC_PATTERN)
    target_cursor_at: str = Field(pattern=UTC_PATTERN)
    reason: str = Field(min_length=3, max_length=500)
    selected_timeframe: str = Field(pattern=TIMEFRAME_PATTERN)


class ReplayV3OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_alias: str = Field(pattern=r"^V3-P-\d{3}$")
    expected_cursor_at: str = Field(pattern=UTC_PATTERN)
    selected_timeframe: str = Field(pattern=TIMEFRAME_PATTERN)
    client_visible_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    direction: ReplayV3Direction
    order_type: ReplayV3OrderType
    entry: float
    stop: float
    target: float
    expiry_at: str | None = Field(default=None, pattern=UTC_PATTERN)
    drawings: list[ReplayV3Drawing] = Field(default_factory=list, max_length=300)
    annotation: ReplayV3Annotation

    @model_validator(mode="after")
    def geometry(self) -> Self:
        values = (self.entry, self.stop, self.target)
        if not all(isfinite(value) for value in values):
            raise ValueError("entry, stop, and target must be finite")
        if self.direction is ReplayV3Direction.LONG and not self.stop < self.entry < self.target:
            raise ValueError("LONG requires stop < entry < target")
        if self.direction is ReplayV3Direction.SHORT and not self.target < self.entry < self.stop:
            raise ValueError("SHORT requires target < entry < stop")
        ids = [drawing.drawing_id for drawing in self.drawings]
        if len(ids) != len(set(ids)):
            raise ValueError("drawing_id values must be unique")
        positions = [
            drawing
            for drawing in self.drawings
            if drawing.kind
            in {ReplayV3DrawingKind.LONG_POSITION, ReplayV3DrawingKind.SHORT_POSITION}
        ]
        if len(positions) != 1:
            raise ValueError("a submitted order requires exactly one position drawing")
        expected = (
            ReplayV3DrawingKind.LONG_POSITION
            if self.direction is ReplayV3Direction.LONG
            else ReplayV3DrawingKind.SHORT_POSITION
        )
        if positions[0].kind is not expected:
            raise ValueError("position drawing direction differs from order direction")
        prices = [anchor.price for anchor in positions[0].anchors]
        if any(abs(left - right) > 1e-8 for left, right in zip(prices, values, strict=True)):
            raise ValueError("position drawing ENTRY/SL/TP differs from order geometry")
        return self


class ReplayV3AmendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_alias: str = Field(pattern=r"^V3-P-\d{3}$")
    expected_cursor_at: str = Field(pattern=UTC_PATTERN)
    client_visible_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    order_type: ReplayV3OrderType
    entry: float
    stop: float
    target: float
    expiry_at: str | None = Field(default=None, pattern=UTC_PATTERN)
    drawings: list[ReplayV3Drawing] = Field(default_factory=list, max_length=300)
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def finite_geometry(self) -> Self:
        if not all(isfinite(value) for value in (self.entry, self.stop, self.target)):
            raise ValueError("amended execution prices must be finite")
        return self


class ReplayV3CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_alias: str = Field(pattern=r"^V3-P-\d{3}$")
    expected_cursor_at: str = Field(pattern=UTC_PATTERN)
    client_visible_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str | None = Field(default=None, max_length=1000)


class ReplayV3ManualCloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_alias: str = Field(pattern=r"^V3-P-\d{3}$")
    expected_cursor_at: str = Field(pattern=UTC_PATTERN)
    client_visible_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=3, max_length=2000)


class ReplayV3StatusResponse(BaseModel):
    protocol: str
    ready: bool
    phase: str
    practice_completed: int
    practice_total: int
    current_case_alias: str | None
    event_ledger_head_sha256: str
    collection_year: int
    collection_state: str
    calendar_2025: str
    calendar_2026: str
    research_credit: str
    practice_cases: list[dict[str, Any]]


class ReplayV3SnapshotResponse(BaseModel):
    case: dict[str, Any]
    progress: ReplayV3StatusResponse


class ReplayV3MutationResponse(BaseModel):
    event_sha256: str
    idempotent_replay: bool
    case: dict[str, Any] | None
    progress: ReplayV3StatusResponse
