from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from gold_intel.analytics.session_edges import SessionEdgeConfig
from gold_intel.backtesting.session_edge_strategy import SessionStrategyConfig


class SessionEdgeConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asia_start_local: str = Field(default="10:05", pattern=r"^\d{2}:\d{2}$")
    asia_end_local: str = Field(default="16:00", pattern=r"^\d{2}:\d{2}$")
    london_start_local: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    london_end_local: str = Field(default="12:00", pattern=r"^\d{2}:\d{2}$")
    fundamental_freeze_minutes_before: int = Field(default=5, ge=0, le=60)
    atr_lookback_bars: int = Field(default=14, ge=2, le=100)
    compression_lookback_sessions: int = Field(default=20, ge=5, le=120)
    compression_min_history: int = Field(default=10, ge=3, le=60)
    compression_threshold_percentile: float = Field(default=50, ge=0, le=100)
    sweep_min_atr: float = Field(default=0.02, ge=0, le=2)
    sweep_max_atr: float = Field(default=0.75, gt=0, le=5)
    reclaim_bars: int = Field(default=2, ge=1, le=12)
    displacement_bars_after_reclaim: int = Field(default=3, ge=1, le=12)
    micro_structure_lookback_bars: int = Field(default=3, ge=1, le=20)
    displacement_min_body_atr: float = Field(default=0.35, ge=0, le=5)
    displacement_min_body_ratio: float = Field(default=0.60, ge=0, le=1)
    displacement_min_close_location: float = Field(default=0.70, ge=0, le=1)
    liquidity_lookback_bars: int = Field(default=100, ge=10, le=1_000)
    stop_buffer_atr: float = Field(default=0.10, ge=0, le=2)
    fundamental_min_score: float = Field(default=5, ge=0, le=100)
    fundamental_min_coverage: float = Field(default=35, ge=0, le=100)
    fundamental_min_confidence: float = Field(default=25, ge=0, le=100)
    outcome_horizons_minutes: tuple[int, ...] = (30, 60, 120, 240)
    target_r_levels: tuple[float, ...] = (0.50, 0.75, 1.00, 2.00)

    @field_validator("outcome_horizons_minutes")
    @classmethod
    def validate_horizons(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if not values or len(set(values)) != len(values):
            raise ValueError("Outcome horizons must be non-empty and unique")
        if any(value <= 0 or value % 5 for value in values):
            raise ValueError("Outcome horizons must be positive multiples of five")
        return tuple(sorted(values))

    @field_validator("target_r_levels")
    @classmethod
    def validate_targets(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        if not values or len(set(values)) != len(values):
            raise ValueError("Target R levels must be non-empty and unique")
        if any(value <= 0 for value in values):
            raise ValueError("Target R levels must be positive")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_relative_bounds(self) -> SessionEdgeConfigRequest:
        if self.sweep_min_atr >= self.sweep_max_atr:
            raise ValueError("sweep_min_atr must be below sweep_max_atr")
        if self.compression_min_history > self.compression_lookback_sessions:
            raise ValueError("compression_min_history cannot exceed compression_lookback_sessions")
        return self

    def to_domain(self) -> SessionEdgeConfig:
        return SessionEdgeConfig(**self.model_dump())


class SessionEdgeStudyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument: str = Field(default="XAUUSD", min_length=1, max_length=64)
    provider_code: str = Field(
        default="IC_MARKETS_MT5",
        min_length=1,
        max_length=64,
    )
    start: datetime
    end: datetime
    include_fundamentals: bool = True
    config: SessionEdgeConfigRequest = Field(default_factory=SessionEdgeConfigRequest)

    @model_validator(mode="after")
    def validate_period(self) -> SessionEdgeStudyRequest:
        _require_timezone(self.start, "start")
        _require_timezone(self.end, "end")
        if self.start >= self.end:
            raise ValueError("start must precede end")
        return self


class SessionOpportunityResponse(BaseModel):
    id: UUID
    run_id: UUID
    session_date: date
    fundamental_freeze_time: datetime
    level_freeze_time: datetime
    london_start_time: datetime
    london_end_time: datetime
    status: str
    no_trigger_reason: str | None
    setup_side: Literal["LONG", "SHORT"] | None
    signal_time: datetime | None
    entry_time: datetime | None
    bias_alignment: str
    directional_score: float | None
    fundamental_confidence: float | None
    fundamental_coverage: float | None
    regime_label: str
    dominant_driver: str | None
    event_risk: str
    asia_high: float | None
    asia_low: float | None
    asia_range_size: float | None
    asia_range_percentile: float | None
    asia_compression_state: str
    entry_reference_price: float | None
    invalidation_price: float | None
    risk_distance: float | None
    facts: dict[str, Any]
    outcomes: list[dict[str, Any]]
    evidence: dict[str, Any]
    data_hash: str
    created_at: datetime


class SessionEdgeStudyRunResponse(BaseModel):
    id: UUID
    strategy_name: str
    strategy_version: str
    instrument: str
    provider_code: str
    start: datetime
    end: datetime
    status: str
    parameters: dict[str, Any]
    data_hash: str
    source_bar_count: int
    session_count: int
    trigger_count: int
    results: dict[str, Any]
    provenance: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None
    opportunities: list[SessionOpportunityResponse]


class SessionEdgeComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_ids: list[UUID] = Field(min_length=2, max_length=10)

    @field_validator("run_ids")
    @classmethod
    def validate_unique_run_ids(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("run_ids must be unique")
        return values


class SessionEdgeComparisonResponse(BaseModel):
    run_ids: list[UUID]
    strategy_name: str
    strategy_version: str
    summary_version: str
    instrument: str
    provider_code: str
    periods: list[dict[str, Any]]
    session_count: int
    trigger_count: int
    summary: dict[str, Any]
    data_hash: str
    interpretation: str


class SessionEdgeStrategyRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_study_run_ids: list[UUID] = Field(min_length=1, max_length=10)
    strategy_mode: Literal[
        "DELAYED_RECLAIM_PRICE_CONTROL",
        "DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED",
    ] = "DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED"
    initial_equity: float = Field(default=10_000, gt=0, le=100_000_000)
    risk_per_trade_pct: float = Field(default=1.0, gt=0, le=5)
    target_r: float = Field(default=1.0, gt=0, le=10)
    max_holding_minutes: int = Field(default=240, ge=30, le=600)
    slippage_price_per_side: float = Field(default=0.05, ge=0, le=20)
    commission_per_lot_round_turn: float = Field(default=7.0, ge=0, le=1_000)
    cost_multiplier: float = Field(default=1.0, gt=0, le=5)
    contract_size: float = Field(default=100.0, gt=0, le=1_000_000)
    min_lot: float = Field(default=0.01, gt=0, le=1_000)
    lot_step: float = Field(default=0.01, gt=0, le=1_000)
    max_lots: float = Field(default=10.0, gt=0, le=100_000)
    allow_unknown_event_risk: bool = True
    calculate_robustness: bool = True

    @field_validator("source_study_run_ids")
    @classmethod
    def validate_unique_source_runs(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("source_study_run_ids must be unique")
        return values

    @model_validator(mode="after")
    def validate_lot_bounds(self) -> SessionEdgeStrategyRunRequest:
        if self.max_lots < self.min_lot:
            raise ValueError("max_lots cannot be below min_lot")
        return self

    def to_domain(self) -> SessionStrategyConfig:
        return SessionStrategyConfig(
            **self.model_dump(exclude={"source_study_run_ids"})
        )


def _require_timezone(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
