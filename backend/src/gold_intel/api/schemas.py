from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class IngestionBatchResponse(BaseModel):
    batch_id: UUID
    provider_code: str
    dataset_code: str
    status: str
    duplicate: bool
    content_hash: str
    record_count: int
    valid_records: int
    invalid_records: int
    quality_issue_count: int
    is_synthetic: bool
    ingested_at: datetime


class IntelligenceCalculationRequest(BaseModel):
    instrument: str = Field(default="XAUUSD", pattern=r"^[A-Z0-9_]{2,32}$")
    as_of: datetime


class SignalResponse(BaseModel):
    id: UUID
    name: str
    layer: int
    driver: str
    epistemic_status: str
    direction: float
    strength: float
    confidence: float
    freshness: float
    data_quality: float
    explanation: str
    observed_at: datetime
    available_at: datetime
    expires_at: datetime | None
    evidence: dict[str, Any]


class IntelligenceSnapshotResponse(BaseModel):
    id: UUID
    instrument: str
    as_of: datetime
    overall_score: float
    bullish_score: float
    bearish_score: float
    neutrality_score: float
    conflict_score: float
    confidence: float
    evidence_coverage: float
    bias: str
    execution_state: str
    dominant_driver: str | None
    main_contradiction: str | None
    ruleset_version: str
    reasoning: dict[str, Any]
    layers: list[dict[str, Any]]
    signal_ids: list[str]


class DataHealthSummaryResponse(BaseModel):
    status: str
    open_issue_count: int
    warning_count: int
    error_count: int
    stale_series: list[str]


class ObservationResponse(BaseModel):
    series_code: str
    observation_time: datetime
    value: float
    unit: str
    available_at: datetime
    vintage: str
    is_revision: bool
    source_record_key: str


class PublicDataSyncRequest(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def validate_period(self) -> PublicDataSyncRequest:
        if self.start >= self.end:
            raise ValueError("start must precede end")
        if self.end - self.start > timedelta(days=3650):
            raise ValueError("one public sync is limited to ten years")
        return self


class PublicDataSyncResponse(BaseModel):
    start: date
    end: date
    fetched_observations: int
    inserted_observations: int
    fetched_cot_reports: int
    inserted_cot_reports: int
    fred_batch_id: UUID
    cftc_batch_id: UUID
    fred_duplicate_batch: bool
    cftc_duplicate_batch: bool


class OfficialCatalystSyncRequest(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def validate_period(self) -> OfficialCatalystSyncRequest:
        if self.start > self.end:
            raise ValueError("start cannot follow end")
        if self.end - self.start > timedelta(days=366):
            raise ValueError("one official catalyst sync is limited to 367 calendar days")
        return self


class OfficialCatalystSyncResponse(BaseModel):
    start: date
    end: date
    retrieved_at: datetime
    fetched_treasury_auctions: int
    inserted_treasury_auctions: int
    treasury_batch_id: UUID | None
    treasury_duplicate_batch: bool | None
    fetched_fed_communications: int
    inserted_fed_communications: int
    fed_batch_id: UUID | None
    fed_duplicate_batch: bool | None


class VintageMacroSyncResponse(BaseModel):
    start: date
    end: date
    fetched_observations: int
    inserted_observations: int
    batch_id: UUID
    duplicate_batch: bool


class TradingEconomicsSyncResponse(BaseModel):
    start: date
    end: date
    fetched_rows: int
    supported_rows: int
    excluded_rows: int
    inserted_events: int
    inserted_forecasts: int
    inserted_releases: int
    calculated_surprises: int
    batch_id: UUID
    duplicate_batch: bool
    retrieved_at: datetime


class CmeFedWatchSyncRequest(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def validate_period(self) -> CmeFedWatchSyncRequest:
        if self.start > self.end:
            raise ValueError("start cannot follow end")
        if self.end - self.start > timedelta(days=366):
            raise ValueError("one CME FedWatch sync is limited to 367 calendar days")
        return self


class CmeFedWatchSyncResponse(BaseModel):
    start: date
    end: date
    fetched_forecast_records: int
    inserted_snapshots: int
    inserted_points: int
    batch_id: UUID
    duplicate_batch: bool
    retrieved_at: datetime


class AtlantaFedMptSyncResponse(BaseModel):
    earliest_observation_date: date
    latest_observation_date: date
    fetched_observation_dates: int
    fetched_windows: int
    inserted_windows: int
    batch_id: UUID
    duplicate_batch: bool
    retrieved_at: datetime
    source_sha256: str
    license_class: str
    availability_quality: str


class FactorCoverageItemResponse(BaseModel):
    code: str
    name: str
    domain: str
    layer: int | None
    declared_epistemic_status: str
    current_epistemic_status: str
    implementation_status: str
    phase1_required: bool
    source_class: str
    record_count: int
    latest_available_at: datetime | None
    age_seconds: int | None
    freshness_status: Literal["FRESH", "STALE", "NOT_APPLICABLE", "UNKNOWN"]
    usable_now: bool
    dependencies: list[str] | tuple[str, ...]
    dependency_mode: Literal["ALL", "ANY"]
    missing_dependencies: list[str] | tuple[str, ...]
    note: str


class FactorCoverageResponse(BaseModel):
    as_of: datetime
    registry_version: str
    registry_hash: str
    total_factors: int
    known_factors: int
    phase1_required_factors: int
    phase1_known_factors: int
    phase1_coverage_pct: float
    book_layer_factors: int
    book_layer_known_factors: int
    book_layer_usable_factors: int
    book_factor_coverage_pct: float
    book_usable_coverage_pct: float
    layers: list[dict[str, Any]]
    factors: list[FactorCoverageItemResponse]


class FundamentalCalculationRequest(BaseModel):
    instrument: str = Field(default="XAUUSD", pattern=r"^[A-Z0-9_.-]{2,32}$")
    as_of: datetime


class FundamentalSnapshotResponse(BaseModel):
    id: UUID
    instrument: str
    as_of: datetime
    directional_score: float
    confidence: float
    coverage: float
    bias: str
    regime: str
    reaction_function: str
    dominant_driver: str | None
    main_contradiction: str | None
    event_risk: str
    upcoming_catalyst: dict[str, Any] | None
    components: list[dict[str, Any]]
    layers: list[dict[str, Any]]
    reasoning: dict[str, Any]
    registry_hash: str
    data_hash: str
    ruleset_version: str
    created_at: datetime


class DecisionCalculationRequest(BaseModel):
    instrument: str = Field(default="XAUUSD", pattern=r"^[A-Z0-9_.-]{2,32}$")
    provider_code: str | None = Field(
        default="IC_MARKETS_MT5",
        pattern=r"^[A-Z0-9_]{2,64}$",
    )
    as_of: datetime
    data_mode: Literal["AUTO", "REAL_ONLY", "SYNTHETIC_ONLY"] = "REAL_ONLY"
    max_source_bars: int = Field(default=60_000, ge=1_000, le=100_000)


class DecisionLayerResponse(BaseModel):
    number: int = Field(ge=1, le=7)
    name: str
    role: Literal["DIRECTIONAL", "EXECUTION_GATE"]
    status: Literal["COMPLETE", "PARTIAL", "UNKNOWN"]
    operational_status: str
    book_factor_count: int = Field(ge=0)
    known_factor_count: int = Field(ge=0)
    usable_factor_count: int = Field(ge=0)
    book_coverage_pct: float = Field(ge=0, le=100)
    phase1_coverage_pct: float = Field(ge=0, le=100)
    directional_contribution: float | None
    confidence: float | None = Field(default=None, ge=0, le=100)
    summary: str
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    unknown_factors: list[str]


class DecisionSnapshotResponse(BaseModel):
    id: UUID
    instrument: str
    provider_code: str | None
    as_of: datetime
    epistemic_status: Literal["INFERRED"]
    directional_score: float = Field(ge=-100, le=100)
    bullish_score: float = Field(ge=0, le=100)
    bearish_score: float = Field(ge=0, le=100)
    neutral_conflict_score: float = Field(ge=0, le=100)
    directional_confidence: float = Field(ge=0, le=100)
    execution_confidence: float = Field(ge=0, le=100)
    directional_evidence_coverage_pct: float = Field(ge=0, le=100)
    phase1_factor_coverage_pct: float = Field(ge=0, le=100)
    book_factor_coverage_pct: float = Field(ge=0, le=100)
    book_usable_coverage_pct: float = Field(ge=0, le=100)
    bias: str
    regime: str
    reaction_function: str
    dominant_driver: str | None
    main_contradiction: str | None
    highest_risk_assumption: str
    upcoming_catalyst: dict[str, Any] | None
    event_risk: str
    current_session: str
    liquidity_state: str
    price_macro_alignment: str
    execution_state: str
    layers: list[DecisionLayerResponse]
    components: list[dict[str, Any]]
    execution_plan: dict[str, Any]
    reasoning: dict[str, Any]
    fundamental_snapshot_id: UUID
    fundamental_data_hash: str
    structure_data_hash: str | None
    registry_hash: str
    data_hash: str
    ruleset_version: str
    created_at: datetime


class PriceBarResponse(BaseModel):
    id: UUID
    instrument: str
    provider: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    volume_type: str
    spread_points: int | None
    spread_price: float | None
    available_at: datetime
    is_complete: bool
    is_synthetic: bool


class StructureDetectionResponse(BaseModel):
    kind: str
    direction: str
    timestamp: datetime
    detected_at: datetime
    price_level: float
    timeframe: str
    detection_method: str
    confidence: float = Field(ge=0, le=100)
    epistemic_status: Literal["CALCULATED", "INFERRED"]
    evidence: dict[str, Any]
    invalidation_condition: str


class TimeframeStructureResponse(BaseModel):
    timeframe: str
    status: str
    source_bar_count: int
    complete_bar_count: int
    last_close: float | None
    atr14: float | None
    trend: str
    support: float | None
    resistance: float | None
    range_low: float | None
    range_high: float | None
    compression_ratio: float | None
    momentum_atr: float | None
    detections: list[StructureDetectionResponse]


class StructureChartBarResponse(BaseModel):
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    complete: bool
    source_ids: list[str]


class StructureSessionRangeResponse(BaseModel):
    name: str
    timezone: str
    start_at: datetime
    end_at: datetime
    status: str
    bar_count: int
    expected_bar_count: int
    completeness_pct: float = Field(ge=0, le=100)
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    range_size: float | None
    breakout_state: str


class StructureSessionResponse(BaseModel):
    primary: str
    active: list[str]
    special_windows: list[str]
    calculated_at: datetime
    evidence: dict[str, str]
    ranges: list[StructureSessionRangeResponse]


class MarketLiquidityResponse(BaseModel):
    as_of: datetime
    latest_bar_at: datetime | None
    primary_session: str
    special_windows: list[str]
    status: Literal["NORMAL", "ELEVATED", "ABNORMAL", "UNKNOWN"]
    epistemic_status: Literal["CALCULATED", "UNKNOWN"]
    ruleset_version: str
    current_window_minutes: int = Field(ge=1)
    current_bar_count: int = Field(ge=0)
    baseline_bar_count: int = Field(ge=0)
    spread_observation_count: int = Field(ge=0)
    current_spread_points: float | None
    current_spread_price: float | None
    current_spread_bps: float | None
    baseline_spread_points: float | None
    p95_spread_points: float | None
    spread_percentile: float | None = Field(default=None, ge=0, le=100)
    current_range_bps: float | None
    baseline_range_bps: float | None
    p95_range_bps: float | None
    range_percentile: float | None = Field(default=None, ge=0, le=100)
    current_tick_volume: float | None
    baseline_tick_volume: float | None
    tick_volume_percentile: float | None = Field(default=None, ge=0, le=100)
    execution_confidence_multiplier: float = Field(ge=0, le=1)
    data_quality_score: float = Field(ge=0, le=100)
    freshness_score: float = Field(ge=0, le=100)
    explanation: str
    evidence: dict[str, Any]
    warnings: list[str]
    data_hash: str


class AuctionSwingResponse(BaseModel):
    identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    timeframe: str
    base_kind: Literal["HIGH", "LOW"]
    classification: str
    pivot_at: datetime
    detected_at: datetime
    price_level: float
    atr14: float
    prominence_atr: float
    confidence: float = Field(ge=0, le=100)
    epistemic_status: Literal["CALCULATED"]
    evidence: dict[str, Any]


class AuctionShiftZoneResponse(BaseModel):
    identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    timeframe: Literal["15m"]
    direction: Literal["BULLISH", "BEARISH"]
    origin_at: datetime
    created_at: datetime
    detected_at: datetime
    lower_bound: float
    upper_bound: float
    midpoint: float
    broken_swing_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    broken_swing_level: float
    creation_atr14: float
    state: str
    first_touch_at: datetime | None
    retest_confirmed_at: datetime | None
    invalidated_at: datetime | None
    expires_at: datetime | None
    epistemic_status: Literal["INFERRED"]
    confidence: float = Field(ge=0, le=100)
    detection_method: str
    invalidation_condition: str
    evidence: dict[str, Any]


class AuctionPaperProposalResponse(BaseModel):
    identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    zone_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    family: Literal["RETEST_LIMIT_V0_1", "CONFIRMED_RETEST_V0_1"]
    direction: Literal["BULLISH", "BEARISH"]
    disposition: str
    triggered_at: datetime | None
    entry_reference: float | None
    stop: float
    target: float | None
    target_swing_identity: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    planned_risk_usd: float | None = Field(default=None, ge=0, le=50)
    quantity_ounces: int | None = Field(default=None, ge=1)
    reward_to_risk: float | None = Field(default=None, ge=0)
    macro_direction: Literal["BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"]
    macro_relationship: str
    liquidity_status: str
    epistemic_status: Literal["INFERRED"]
    explanation: str
    evidence: dict[str, Any]


class AuctionAutomationResponse(BaseModel):
    as_of: datetime
    ruleset_version: str
    config: dict[str, float | int]
    source_bar_count: int = Field(ge=0)
    source_first_at: datetime | None
    source_last_at: datetime | None
    data_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    macro_direction: Literal["BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"]
    macro_bias_label: str
    macro_available_at: datetime | None
    liquidity_status: str
    timeframe_trends: dict[str, str]
    swings: list[AuctionSwingResponse]
    zones: list[AuctionShiftZoneResponse]
    proposals: list[AuctionPaperProposalResponse]
    warnings: list[str]


class MarketStructureSnapshotResponse(BaseModel):
    instrument: str
    provider_code: str
    provider_session_template: str
    data_mode: Literal["REAL_ONLY", "SYNTHETIC_ONLY"]
    is_synthetic: bool
    as_of: datetime
    latest_bar_at: datetime
    generated_at: datetime
    source_staleness_seconds: int
    ruleset_version: str
    config: dict[str, float | int]
    source_bar_count: int
    data_hash: str
    session: StructureSessionResponse
    liquidity: MarketLiquidityResponse
    auction_automation: AuctionAutomationResponse
    timeframes: list[TimeframeStructureResponse]
    chart_bars: list[StructureChartBarResponse]


class BacktestRunRequest(BaseModel):
    instrument: str = Field(default="XAUUSD", pattern=r"^[A-Z0-9_.-]{2,32}$")
    provider_code: str = Field(default="IC_MARKETS_MT5", pattern=r"^[A-Z0-9_]{2,64}$")
    strategy_mode: Literal["PRICE_ONLY_CONTROL", "FUNDAMENTAL_ALIGNED"] = "PRICE_ONLY_CONTROL"
    start: datetime
    end: datetime
    initial_equity: float = Field(default=10_000, gt=0, le=100_000_000)
    risk_per_trade_pct: float = Field(default=1.0, gt=0, le=5)
    asia_start_local: str = Field(
        default="10:05",
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
    )
    asia_end_local: str = Field(
        default="16:00",
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
    )
    confirmation_bars: int = Field(default=2, ge=1, le=3)
    breakout_buffer_atr: float = Field(default=0.10, ge=0, le=2)
    stop_atr_multiple: float = Field(default=1.50, gt=0, le=10)
    target_r: float = Field(default=2.0, gt=0, le=20)
    spread_price: float = Field(default=0.30, ge=0, le=20)
    slippage_price: float = Field(default=0.05, ge=0, le=20)
    commission_per_lot_round_turn: float = Field(default=7.0, ge=0, le=1_000)
    contract_size: float = Field(default=100.0, gt=0, le=1_000_000)
    min_lot: float = Field(default=0.01, gt=0, le=1_000)
    lot_step: float = Field(default=0.01, gt=0, le=1_000)
    max_lots: float = Field(default=10.0, gt=0, le=100_000)
    fundamental_min_score: float = Field(default=5.0, ge=0, le=100)
    fundamental_min_coverage: float = Field(default=35.0, ge=0, le=100)
    fundamental_min_confidence: float = Field(default=25.0, ge=0, le=100)
    block_high_impact_events: bool = True
    allow_unknown_event_risk: bool = False
    block_elevated_or_abnormal_liquidity: bool = True
    allow_unknown_liquidity: bool = False

    @model_validator(mode="after")
    def validate_period(self) -> BacktestRunRequest:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end must include a timezone")
        if self.start >= self.end:
            raise ValueError("start must precede end")
        if self.end - self.start > timedelta(days=120):
            raise ValueError("the first backtest slice is limited to 120 days")
        asia_start = time.fromisoformat(self.asia_start_local)
        asia_end = time.fromisoformat(self.asia_end_local)
        if asia_start >= asia_end:
            raise ValueError("asia_start_local must precede asia_end_local")
        if asia_start.minute % 5 or asia_end.minute % 5:
            raise ValueError("Asia session times must align to five-minute boundaries")
        if self.max_lots < self.min_lot:
            raise ValueError("max_lots cannot be below min_lot")
        return self


class BacktestTradeResponse(BaseModel):
    sequence: int
    side: str
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    quantity_lots: float
    exit_reason: str
    gross_pnl: float
    costs: float
    net_pnl: float
    r_multiple: float
    mfe_r: float
    mae_r: float
    holding_minutes: int
    evidence: dict[str, Any]


class BacktestRunResponse(BaseModel):
    id: UUID
    strategy: str
    strategy_version: str
    instrument: str
    provider_code: str
    start: datetime
    end: datetime
    status: str
    parameters: dict[str, Any]
    data_hash: str
    source_bar_count: int
    metrics: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    provenance: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None
    trades: list[BacktestTradeResponse]


class BacktestDataRangeResponse(BaseModel):
    instrument: str
    provider_code: str
    earliest: datetime | None
    latest: datetime | None
    bar_count: int
    ready: bool


class EconomicForecastInput(BaseModel):
    component_code: str = Field(pattern=r"^[A-Z0-9_]{2,96}$")
    forecast_value: float
    unit: str = Field(min_length=1, max_length=64)
    forecast_as_of: datetime
    available_at: datetime
    provider_code: str = Field(
        default="MANUAL_CONSENSUS",
        pattern=r"^[A-Z0-9_]{2,64}$",
    )
    vintage: str = Field(min_length=1, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_availability(self) -> EconomicForecastInput:
        _require_timezone(self.forecast_as_of, "forecast_as_of")
        _require_timezone(self.available_at, "available_at")
        if self.available_at < self.forecast_as_of:
            raise ValueError("forecast available_at cannot precede forecast_as_of")
        return self


class EconomicReleaseInput(BaseModel):
    component_code: str = Field(pattern=r"^[A-Z0-9_]{2,96}$")
    observation_period: date
    actual_value: float
    previous_value: float | None = None
    revised_previous_value: float | None = None
    unit: str = Field(min_length=1, max_length=64)
    released_at: datetime
    available_at: datetime
    is_revision: bool = False
    vintage: str = Field(min_length=1, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_availability(self) -> EconomicReleaseInput:
        _require_timezone(self.released_at, "released_at")
        _require_timezone(self.available_at, "available_at")
        if self.available_at < self.released_at:
            raise ValueError("release available_at cannot precede released_at")
        if self.observation_period > self.released_at.date():
            raise ValueError("observation_period cannot be after released_at")
        return self


class EconomicEventInput(BaseModel):
    event_code: str = Field(pattern=r"^[A-Z0-9_]{2,96}$")
    name: str = Field(min_length=2, max_length=255)
    event_type: str = Field(pattern=r"^[A-Z0-9_]{2,64}$")
    scheduled_at: datetime
    released_at: datetime | None = None
    importance: int = Field(ge=1, le=5)
    is_scheduled: bool = True
    status: Literal["SCHEDULED", "RELEASED", "REVISED", "CANCELLED"]
    source_event_key: str = Field(min_length=1, max_length=255)
    available_at: datetime
    forecasts: list[EconomicForecastInput] = Field(default_factory=list, max_length=50)
    releases: list[EconomicReleaseInput] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_point_in_time_contract(self) -> EconomicEventInput:
        _require_timezone(self.scheduled_at, "scheduled_at")
        _require_timezone(self.available_at, "available_at")
        if self.released_at is not None:
            _require_timezone(self.released_at, "released_at")
        original_releases = [release for release in self.releases if not release.is_revision]
        metadata_only_types = {
            "FED_SPEECH",
            "FED_TESTIMONY",
            "FED_MONETARY_POLICY_RELEASE",
            "FOMC_MINUTES",
            "FOMC_PROJECTIONS",
            "FOMC_STATEMENT",
        }
        metadata_only_release = (
            self.status == "RELEASED"
            and self.event_type in metadata_only_types
            and self.released_at is not None
            and not self.releases
        )
        if (
            self.status in {"RELEASED", "REVISED"}
            and not original_releases
            and not metadata_only_release
        ):
            raise ValueError("released events require an original release record")
        if self.status == "SCHEDULED" and original_releases:
            raise ValueError("a scheduled event cannot contain an original release")
        if self.released_at is not None and original_releases:
            first_release = min(release.released_at for release in original_releases)
            if self.released_at != first_release:
                raise ValueError(
                    "event released_at must match the first original release timestamp"
                )
        elif original_releases:
            raise ValueError("event released_at is required when a release is present")
        if metadata_only_release:
            assert self.released_at is not None
            if self.available_at < self.released_at:
                raise ValueError(
                    "metadata-only release available_at cannot precede released_at"
                )

        release_cutoff = (
            min(release.released_at for release in original_releases)
            if original_releases
            else self.released_at or self.scheduled_at
        )
        for forecast in self.forecasts:
            if forecast.forecast_as_of > release_cutoff:
                raise ValueError("forecast_as_of must not be after the release")
            if forecast.available_at > release_cutoff:
                raise ValueError("forecast available_at must not be after the release")
        return self


class EconomicEventBundleRequest(BaseModel):
    provider_code: str = Field(
        default="MANUAL_EVENT_UPLOAD",
        pattern=r"^[A-Z0-9_]{2,64}$",
    )
    dataset_code: str = Field(
        default="ECONOMIC_EVENT_BUNDLE",
        pattern=r"^[A-Z0-9_]{2,96}$",
    )
    schema_version: str = Field(default="1.0", min_length=1, max_length=32)
    is_synthetic: bool = False
    source_published_at: datetime | None = None
    events: list[EconomicEventInput] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_bundle(self) -> EconomicEventBundleRequest:
        if self.source_published_at is not None:
            _require_timezone(self.source_published_at, "source_published_at")
        keys = [(event.source_event_key, event.available_at) for event in self.events]
        if len(keys) != len(set(keys)):
            raise ValueError("event source_event_key/available_at pairs must be unique")
        return self


class EconomicEventBundleResponse(BaseModel):
    batch_id: UUID
    provider_code: str
    dataset_code: str
    content_hash: str
    duplicate: bool
    event_count: int
    forecast_count: int
    release_count: int
    surprise_count: int
    surprise_exclusions: list[dict[str, Any]]
    is_synthetic: bool
    ingested_at: datetime


class EconomicSurpriseCalculationRequest(BaseModel):
    as_of: datetime
    data_mode: Literal["REAL_ONLY", "SYNTHETIC_ONLY"] = "REAL_ONLY"

    @model_validator(mode="after")
    def validate_as_of(self) -> EconomicSurpriseCalculationRequest:
        _require_timezone(self.as_of, "as_of")
        return self


class EconomicSurpriseResponse(BaseModel):
    id: UUID
    event_id: UUID
    release_id: UUID
    forecast_id: UUID
    event_code: str
    event_name: str
    component_code: str
    released_at: datetime
    available_at: datetime
    raw_surprise: float
    standardized_surprise: float
    gold_direction: float
    strength: float
    confidence: float
    history_count: int
    method: str
    epistemic_status: str
    explanation: str
    evidence: dict[str, Any]
    ruleset_version: str
    data_hash: str
    is_synthetic: bool


class EconomicSurpriseBatchResponse(BaseModel):
    as_of: datetime
    data_mode: str
    calculated_count: int
    inserted_count: int
    exclusions: list[dict[str, Any]]
    surprises: list[EconomicSurpriseResponse]


class EconomicEventResponse(BaseModel):
    id: UUID
    event_code: str
    name: str
    event_type: str
    scheduled_at: datetime
    released_at: datetime | None
    importance: int
    status: str
    provider_code: str
    source_event_key: str
    available_at: datetime
    is_synthetic: bool
    forecasts: list[dict[str, Any]]
    releases: list[dict[str, Any]]


class EventStudyRunRequest(BaseModel):
    instrument: str = Field(default="XAUUSD", pattern=r"^[A-Z0-9_.-]{2,32}$")
    provider_code: str = Field(
        default="IC_MARKETS_MT5",
        pattern=r"^[A-Z0-9_]{2,64}$",
    )
    start: datetime
    end: datetime
    study_as_of: datetime
    data_mode: Literal["REAL_ONLY", "SYNTHETIC_ONLY"] = "REAL_ONLY"
    minimum_importance: int = Field(default=3, ge=1, le=5)
    component_codes: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_period(self) -> EventStudyRunRequest:
        for field_name in ("start", "end", "study_as_of"):
            _require_timezone(getattr(self, field_name), field_name)
        if self.start >= self.end:
            raise ValueError("start must precede end")
        if self.end - self.start > timedelta(days=1096):
            raise ValueError("one event study is limited to three years")
        if self.study_as_of < self.end:
            raise ValueError("study_as_of cannot precede the selected event period end")
        invalid_codes = [
            code for code in self.component_codes if not code.replace("_", "").isalnum()
        ]
        if invalid_codes:
            raise ValueError("component_codes must contain only A-Z, 0-9, and underscore")
        return self


class EventStudyRunResponse(BaseModel):
    id: UUID
    instrument: str
    provider_code: str
    start: datetime
    end: datetime
    status: str
    parameters: dict[str, Any]
    data_hash: str
    candidate_count: int
    eligible_count: int
    exclusions: dict[str, Any]
    results: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None


class PolicyPathOutcomeInput(BaseModel):
    meeting_date: date
    outcome_basis_points: int = Field(ge=0, le=2000)
    probability: float = Field(ge=0, le=1)
    expected_rate: float | None = Field(default=None, ge=0, le=20)
    source_record_key: str = Field(min_length=1, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyPathSnapshotInput(BaseModel):
    snapshot_as_of: datetime
    available_at: datetime
    outcomes: list[PolicyPathOutcomeInput] = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_snapshot(self) -> PolicyPathSnapshotInput:
        _require_timezone(self.snapshot_as_of, "snapshot_as_of")
        _require_timezone(self.available_at, "available_at")
        if self.available_at < self.snapshot_as_of:
            raise ValueError("available_at cannot precede snapshot_as_of")
        grouped: dict[date, float] = {}
        keys: set[tuple[date, int]] = set()
        for outcome in self.outcomes:
            key = (outcome.meeting_date, outcome.outcome_basis_points)
            if key in keys:
                raise ValueError("meeting/outcome pairs must be unique")
            keys.add(key)
            grouped[outcome.meeting_date] = (
                grouped.get(outcome.meeting_date, 0.0) + outcome.probability
            )
        invalid = {
            meeting.isoformat(): total
            for meeting, total in grouped.items()
            if abs(total - 1.0) > 0.001
        }
        if invalid:
            raise ValueError(
                "outcome probabilities must sum to 1 for each meeting: " + str(invalid)
            )
        return self


class PolicyPathBundleRequest(BaseModel):
    provider_code: str = Field(
        default="MANUAL_POLICY_PATH",
        pattern=r"^[A-Z0-9_]{2,64}$",
    )
    dataset_code: str = Field(
        default="FED_POLICY_PATH",
        pattern=r"^[A-Z0-9_]{2,96}$",
    )
    schema_version: str = Field(default="1.0", min_length=1, max_length=32)
    is_synthetic: bool = False
    snapshots: list[PolicyPathSnapshotInput] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_bundle(self) -> PolicyPathBundleRequest:
        keys = [(snapshot.snapshot_as_of, snapshot.available_at) for snapshot in self.snapshots]
        if len(keys) != len(set(keys)):
            raise ValueError("snapshot timestamps must be unique within a bundle")
        return self


class PolicyPathBundleResponse(BaseModel):
    batch_id: UUID
    provider_code: str
    dataset_code: str
    content_hash: str
    duplicate: bool
    snapshot_count: int
    point_count: int
    is_synthetic: bool
    ingested_at: datetime


class PolicyPathResponse(BaseModel):
    provider_code: str
    snapshot_as_of: datetime
    available_at: datetime
    is_synthetic: bool
    meetings: list[dict[str, Any]]


class QuarterlyPolicyExpectationResponse(BaseModel):
    provider_code: str
    observation_date: date
    snapshot_as_of: datetime
    available_at: datetime
    availability_quality: str
    reference_start: date
    reference_end: date
    target_range_basis_points: list[int]
    rate_distribution_basis_points: dict[str, float]
    probability_cut: float | None
    probability_hike: float | None
    probability_bins: list[dict[str, Any]]
    distribution_probability_sum: float | None
    source_record_key: str
    is_synthetic: bool
    semantics: Literal["QUARTERLY_AVERAGE_SOFR_DISTRIBUTION"]
    is_exact_fomc_meeting_probability: Literal[False]


def _require_timezone(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
