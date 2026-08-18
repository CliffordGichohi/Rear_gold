from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gold_intel.infrastructure.database import Base


class Provider(Base):
    __tablename__ = "providers"
    __table_args__ = {"schema": "catalog"}

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    license_class: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ProviderOAuthConnection(Base):
    __tablename__ = "provider_oauth_connections"
    __table_args__ = (
        UniqueConstraint(
            "provider_code",
            "environment",
            name="uq_provider_oauth_connection",
        ),
        CheckConstraint(
            "status IN ('AUTHORIZED', 'EXPIRED', 'REVOKED')",
            name="ck_provider_oauth_connection_status",
        ),
        {"schema": "ops"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    token_type: Mapped[str] = mapped_column(String(16), nullable=False)
    encryption_version: Mapped[str] = mapped_column(String(16), nullable=False)
    access_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProviderOAuthAuditEvent(Base):
    __tablename__ = "provider_oauth_audit_events"
    __table_args__ = {"schema": "ops"}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("ops.provider_oauth_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = {"schema": "catalog"}

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(64), nullable=False)
    price_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    tick_size: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Series(Base):
    __tablename__ = "series"
    __table_args__ = {"schema": "catalog"}

    code: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    frequency: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_lag_seconds: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"
    __table_args__ = (
        UniqueConstraint("provider_code", "dataset_code", "content_hash"),
        {"schema": "raw"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_code: Mapped[str] = mapped_column(String(96), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_object_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RECEIVED")
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RawRecord(Base):
    __tablename__ = "raw_records"
    __table_args__ = (
        UniqueConstraint("batch_id", "record_number"),
        {"schema": "raw"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"), nullable=False
    )
    record_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_record_key: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    parsed_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    parse_error: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PriceBar(Base):
    __tablename__ = "price_bars"
    __table_args__ = (
        CheckConstraint("close_time > open_time", name="ck_price_bar_time_order"),
        CheckConstraint(
            "high >= open AND high >= close AND high >= low AND low <= open AND low <= close",
            name="ck_price_bar_ohlc_geometry",
        ),
        CheckConstraint(
            "spread_points IS NULL OR spread_points >= 0",
            name="ck_price_bar_spread_points",
        ),
        CheckConstraint(
            "spread_price IS NULL OR spread_price >= 0",
            name="ck_price_bar_spread_price",
        ),
        UniqueConstraint(
            "provider_code",
            "instrument_code",
            "timeframe",
            "open_time",
            "available_at",
        ),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_code: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    volume_type: Mapped[str] = mapped_column(String(32), nullable=False)
    spread_points: Mapped[int | None] = mapped_column(Integer)
    spread_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"), nullable=False
    )
    source_record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("series_code", "observation_time", "available_at", "vintage"),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    observation_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    series_code: Mapped[str] = mapped_column(String(96), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    vintage: Mapped[str] = mapped_column(String(64), nullable=False)
    is_revision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supersedes_id: Mapped[UUID | None] = mapped_column()
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"), nullable=False
    )
    source_record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class EconomicEvent(Base):
    __tablename__ = "economic_events"
    __table_args__ = (
        CheckConstraint("importance >= 1 AND importance <= 5", name="ck_event_importance"),
        UniqueConstraint("provider_code", "source_event_key", "available_at"),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_code: Mapped[str] = mapped_column(String(96), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    importance: Mapped[int] = mapped_column(Integer, nullable=False)
    is_scheduled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    batch_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT")
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ForecastSnapshot(Base):
    __tablename__ = "forecast_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "event_code",
            "scheduled_at",
            "component_code",
            "provider_code",
            "available_at",
            "vintage",
        ),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_code: Mapped[str] = mapped_column(String(96), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    component_code: Mapped[str] = mapped_column(String(96), nullable=False)
    forecast_value: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    forecast_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    vintage: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT")
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EconomicRelease(Base):
    __tablename__ = "economic_releases"
    __table_args__ = (
        UniqueConstraint("event_id", "component_code", "available_at", "vintage"),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("market.economic_events.id", ondelete="RESTRICT"), nullable=False
    )
    component_code: Mapped[str] = mapped_column(String(96), nullable=False)
    observation_period: Mapped[date] = mapped_column(Date, nullable=False)
    actual_value: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    previous_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    revised_previous_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    vintage: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT")
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PolicyPathPoint(Base):
    __tablename__ = "policy_path_points"
    __table_args__ = (
        CheckConstraint("probability >= 0 AND probability <= 1", name="ck_policy_path_probability"),
        UniqueConstraint(
            "provider_code",
            "snapshot_as_of",
            "meeting_date",
            "outcome_basis_points",
            "available_at",
        ),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    meeting_date: Mapped[date] = mapped_column(Date, nullable=False)
    outcome_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    probability: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    expected_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    batch_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT")
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PolicyExpectationWindow(Base):
    __tablename__ = "policy_expectation_windows"
    __table_args__ = (
        CheckConstraint(
            "reference_end >= reference_start",
            name="ck_policy_expectation_reference_order",
        ),
        CheckConstraint(
            "available_at > snapshot_as_of",
            name="ck_policy_expectation_availability_order",
        ),
        CheckConstraint(
            "target_upper_basis_points >= target_lower_basis_points",
            name="ck_policy_expectation_target_range",
        ),
        CheckConstraint(
            "probability_cut IS NULL OR (probability_cut >= 0 AND probability_cut <= 1)",
            name="ck_policy_expectation_cut_probability",
        ),
        CheckConstraint(
            "probability_hike IS NULL OR (probability_hike >= 0 AND probability_hike <= 1)",
            name="ck_policy_expectation_hike_probability",
        ),
        CheckConstraint(
            "distribution_probability_sum IS NULL OR "
            "(distribution_probability_sum >= 0 AND distribution_probability_sum <= 1.01)",
            name="ck_policy_expectation_probability_sum",
        ),
        UniqueConstraint(
            "provider_code",
            "observation_date",
            "reference_start",
            "available_at",
        ),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    snapshot_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference_start: Mapped[date] = mapped_column(Date, nullable=False)
    reference_end: Mapped[date] = mapped_column(Date, nullable=False)
    target_lower_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    target_upper_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    rate_p25_basis_points: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    rate_mean_basis_points: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    rate_mode_basis_points: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    rate_p75_basis_points: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    probability_cut: Mapped[Decimal | None] = mapped_column(Numeric(12, 10))
    probability_hike: Mapped[Decimal | None] = mapped_column(Numeric(12, 10))
    probability_bins: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    distribution_probability_sum: Mapped[Decimal | None] = mapped_column(Numeric(12, 10))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    availability_quality: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"), nullable=False
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CotReport(Base):
    __tablename__ = "cot_reports"
    __table_args__ = (
        CheckConstraint(
            "publication_at > observation_date", name="ck_cot_publication_after_observation"
        ),
        UniqueConstraint(
            "provider_code",
            "report_type",
            "contract_market_code",
            "observation_date",
            "publication_at",
        ),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    report_type: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_market_code: Mapped[str] = mapped_column(String(32), nullable=False)
    market_name: Mapped[str] = mapped_column(String(255), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    publication_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open_interest: Mapped[int] = mapped_column(Integer, nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    availability_quality: Mapped[str] = mapped_column(String(32), nullable=False)
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"), nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CotPosition(Base):
    __tablename__ = "cot_positions"
    __table_args__ = (
        CheckConstraint("long_contracts >= 0", name="ck_cot_long_nonnegative"),
        CheckConstraint("short_contracts >= 0", name="ck_cot_short_nonnegative"),
        UniqueConstraint("report_id", "category"),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    report_id: Mapped[UUID] = mapped_column(
        ForeignKey("market.cot_reports.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    long_contracts: Mapped[int] = mapped_column(Integer, nullable=False)
    short_contracts: Mapped[int] = mapped_column(Integer, nullable=False)
    spreading_contracts: Mapped[int | None] = mapped_column(Integer)
    percent_open_interest_long: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    percent_open_interest_short: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    traders_long: Mapped[int | None] = mapped_column(Integer)
    traders_short: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class PositioningObservation(Base):
    __tablename__ = "positioning_observations"
    __table_args__ = (
        UniqueConstraint(
            "instrument_code",
            "metric_code",
            "observation_time",
            "available_at",
            "provider_code",
            "vintage",
        ),
        {"schema": "market"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    instrument_code: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(96), nullable=False)
    observation_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    vintage: Mapped[str] = mapped_column(String(64), nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(16), nullable=False)
    batch_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT")
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint("direction >= -1 AND direction <= 1", name="ck_signal_direction"),
        CheckConstraint("strength >= 0 AND strength <= 100", name="ck_signal_strength"),
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_signal_confidence"),
        CheckConstraint("freshness >= 0 AND freshness <= 100", name="ck_signal_freshness"),
        CheckConstraint("data_quality >= 0 AND data_quality <= 100", name="ck_signal_quality"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    layer: Mapped[int] = mapped_column(Integer, nullable=False)
    driver: Mapped[str] = mapped_column(String(96), nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    strength: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    freshness: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    data_quality: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    contradicting_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ruleset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"
    __table_args__ = (
        CheckConstraint("overall_score >= -100 AND overall_score <= 100", name="ck_score_total"),
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_score_confidence"),
        CheckConstraint("coverage >= 0 AND coverage <= 100", name="ck_score_coverage"),
        UniqueConstraint("instrument_code", "as_of", "ruleset_version"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    instrument_code: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    overall_score: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    bullish_score: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    bearish_score: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    neutrality_score: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    conflict_score: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    coverage: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    bias_label: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_state: Mapped[str] = mapped_column(String(32), nullable=False)
    dominant_driver: Mapped[str | None] = mapped_column(String(96))
    main_contradiction: Mapped[str | None] = mapped_column(String(128))
    reasoning: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    layers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    signal_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FundamentalSnapshot(Base):
    __tablename__ = "fundamental_snapshots"
    __table_args__ = (
        CheckConstraint(
            "directional_score >= -100 AND directional_score <= 100",
            name="ck_fundamental_score",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_fundamental_confidence"),
        CheckConstraint("coverage >= 0 AND coverage <= 100", name="ck_fundamental_coverage"),
        UniqueConstraint("instrument_code", "as_of", "ruleset_version", "data_hash"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    instrument_code: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    directional_score: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    coverage: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    bias_label: Mapped[str] = mapped_column(String(32), nullable=False)
    regime_label: Mapped[str] = mapped_column(String(64), nullable=False)
    reaction_function: Mapped[str] = mapped_column(String(64), nullable=False)
    dominant_driver: Mapped[str | None] = mapped_column(String(96))
    main_contradiction: Mapped[str | None] = mapped_column(Text)
    event_risk: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    upcoming_catalyst: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    layers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    reasoning: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    registry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DecisionSnapshot(Base):
    __tablename__ = "decision_snapshots"
    __table_args__ = (
        CheckConstraint(
            "directional_score >= -100 AND directional_score <= 100",
            name="ck_decision_directional_score",
        ),
        CheckConstraint(
            "bullish_score >= 0 AND bullish_score <= 100",
            name="ck_decision_bullish_score",
        ),
        CheckConstraint(
            "bearish_score >= 0 AND bearish_score <= 100",
            name="ck_decision_bearish_score",
        ),
        CheckConstraint(
            "neutral_conflict_score >= 0 AND neutral_conflict_score <= 100",
            name="ck_decision_neutral_conflict_score",
        ),
        CheckConstraint(
            "directional_confidence >= 0 AND directional_confidence <= 100",
            name="ck_decision_directional_confidence",
        ),
        CheckConstraint(
            "execution_confidence >= 0 AND execution_confidence <= 100",
            name="ck_decision_execution_confidence",
        ),
        CheckConstraint(
            "directional_evidence_coverage_pct >= 0 "
            "AND directional_evidence_coverage_pct <= 100",
            name="ck_decision_directional_coverage",
        ),
        CheckConstraint(
            "phase1_factor_coverage_pct >= 0 AND phase1_factor_coverage_pct <= 100",
            name="ck_decision_phase1_coverage",
        ),
        CheckConstraint(
            "book_factor_coverage_pct >= 0 AND book_factor_coverage_pct <= 100",
            name="ck_decision_book_coverage",
        ),
        CheckConstraint(
            "book_usable_coverage_pct >= 0 AND book_usable_coverage_pct <= 100",
            name="ck_decision_book_usable_coverage",
        ),
        UniqueConstraint(
            "instrument_code",
            "as_of",
            "ruleset_version",
            "data_hash",
            name="uq_decision_snapshot_evidence",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    instrument_code: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_code: Mapped[str | None] = mapped_column(String(64))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(16), nullable=False)
    directional_score: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    bullish_score: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    bearish_score: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    neutral_conflict_score: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    directional_confidence: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    execution_confidence: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    directional_evidence_coverage_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), nullable=False
    )
    phase1_factor_coverage_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), nullable=False
    )
    book_factor_coverage_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), nullable=False
    )
    book_usable_coverage_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), nullable=False
    )
    bias_label: Mapped[str] = mapped_column(String(32), nullable=False)
    regime_label: Mapped[str] = mapped_column(String(64), nullable=False)
    reaction_function: Mapped[str] = mapped_column(String(64), nullable=False)
    dominant_driver: Mapped[str | None] = mapped_column(String(96))
    main_contradiction: Mapped[str | None] = mapped_column(Text)
    highest_risk_assumption: Mapped[str] = mapped_column(Text, nullable=False)
    upcoming_catalyst: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    event_risk: Mapped[str] = mapped_column(String(24), nullable=False)
    current_session: Mapped[str] = mapped_column(String(64), nullable=False)
    liquidity_state: Mapped[str] = mapped_column(String(24), nullable=False)
    price_macro_alignment: Mapped[str] = mapped_column(String(24), nullable=False)
    execution_state: Mapped[str] = mapped_column(String(64), nullable=False)
    layers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    execution_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reasoning: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fundamental_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("analytics.fundamental_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    fundamental_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    structure_data_hash: Mapped[str | None] = mapped_column(String(64))
    registry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EconomicSurprise(Base):
    __tablename__ = "economic_surprises"
    __table_args__ = (
        CheckConstraint(
            "gold_direction >= -1 AND gold_direction <= 1",
            name="ck_surprise_gold_direction",
        ),
        CheckConstraint(
            "strength >= 0 AND strength <= 100",
            name="ck_surprise_strength",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_surprise_confidence",
        ),
        UniqueConstraint(
            "release_id",
            "forecast_id",
            "ruleset_version",
            "data_hash",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("market.economic_events.id", ondelete="RESTRICT"), nullable=False
    )
    release_id: Mapped[UUID] = mapped_column(
        ForeignKey("market.economic_releases.id", ondelete="RESTRICT"), nullable=False
    )
    forecast_id: Mapped[UUID] = mapped_column(
        ForeignKey("market.forecast_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    component_code: Mapped[str] = mapped_column(String(96), nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_surprise: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    standardized_surprise: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    gold_direction: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    strength: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    history_count: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(16), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventReaction(Base):
    __tablename__ = "event_reactions"
    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "instrument_code",
            "provider_code",
            "horizon_code",
            "calculation_version",
            "data_hash",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("market.economic_events.id", ondelete="RESTRICT"), nullable=False
    )
    release_id: Mapped[UUID] = mapped_column(
        ForeignKey("market.economic_releases.id", ondelete="RESTRICT"), nullable=False
    )
    surprise_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("analytics.economic_surprises.id", ondelete="RESTRICT")
    )
    instrument_code: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    horizon_code: Mapped[str] = mapped_column(String(24), nullable=False)
    reference_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    horizon_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    price_change: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    return_pct: Mapped[Decimal] = mapped_column(Numeric(16, 8), nullable=False)
    mfe_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    mae_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    first_move_direction: Mapped[str] = mapped_column(String(8), nullable=False)
    first_move_held: Mapped[bool | None] = mapped_column(Boolean)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventStudyRun(Base):
    __tablename__ = "event_study_runs"
    __table_args__ = {"schema": "analytics"}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    instrument_code: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    exclusions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionEdgeStudyRun(Base):
    __tablename__ = "session_edge_study_runs"
    __table_args__ = {"schema": "analytics"}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_code: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_bar_count: Mapped[int] = mapped_column(Integer, nullable=False)
    session_count: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False)
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionOpportunity(Base):
    __tablename__ = "session_opportunities"
    __table_args__ = (
        UniqueConstraint("run_id", "session_date"),
        CheckConstraint(
            "directional_score IS NULL OR "
            "(directional_score >= -100 AND directional_score <= 100)",
            name="ck_session_opportunity_directional_score",
        ),
        CheckConstraint(
            "fundamental_confidence IS NULL OR "
            "(fundamental_confidence >= 0 AND fundamental_confidence <= 100)",
            name="ck_session_opportunity_fundamental_confidence",
        ),
        CheckConstraint(
            "fundamental_coverage IS NULL OR "
            "(fundamental_coverage >= 0 AND fundamental_coverage <= 100)",
            name="ck_session_opportunity_fundamental_coverage",
        ),
        CheckConstraint(
            "asia_range_percentile IS NULL OR "
            "(asia_range_percentile >= 0 AND asia_range_percentile <= 100)",
            name="ck_session_opportunity_asia_percentile",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analytics.session_edge_study_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    fundamental_freeze_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    level_freeze_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    london_start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    london_end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    no_trigger_reason: Mapped[str | None] = mapped_column(String(96))
    setup_side: Mapped[str | None] = mapped_column(String(8))
    signal_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bias_alignment: Mapped[str] = mapped_column(String(40), nullable=False)
    directional_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    fundamental_confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    fundamental_coverage: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    regime_label: Mapped[str] = mapped_column(String(64), nullable=False)
    dominant_driver: Mapped[str | None] = mapped_column(String(96))
    event_risk: Mapped[str] = mapped_column(String(24), nullable=False)
    asia_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    asia_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    asia_range_size: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    asia_range_percentile: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    asia_compression_state: Mapped[str] = mapped_column(String(24), nullable=False)
    entry_reference_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    invalidation_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    risk_distance: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outcomes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = {"schema": "analytics"}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_code: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_bar_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    equity_curve: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analytics.backtest_runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    stop_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    target_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity_lots: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    exit_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    costs: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    r_multiple: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    mfe_r: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    mae_r: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    holding_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    __table_args__ = {"schema": "ops"}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    batch_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT")
    )
    code: Mapped[str] = mapped_column(String(96), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("job_key"), {"schema": "ops"})

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_key: Mapped[str] = mapped_column(String(128), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
