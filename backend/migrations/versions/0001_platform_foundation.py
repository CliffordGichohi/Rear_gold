"""Create the platform foundation and first-slice tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_platform_foundation"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    for schema in ("catalog", "raw", "market", "analytics", "ops"):
        op.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    op.create_table(
        "providers",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("provider_type", sa.String(64), nullable=False),
        sa.Column("license_class", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        schema="catalog",
    )
    op.create_table(
        "instruments",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("asset_class", sa.String(64), nullable=False),
        sa.Column("price_currency", sa.String(16), nullable=False),
        sa.Column("tick_size", sa.Numeric(18, 8), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        schema="catalog",
    )
    op.create_table(
        "series",
        sa.Column("code", sa.String(96), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("frequency", sa.String(32), nullable=False),
        sa.Column("expected_lag_seconds", sa.Integer()),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        schema="catalog",
    )
    op.create_table(
        "ingestion_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("dataset_code", sa.String(96), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_object_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("provider_code", "dataset_code", "content_hash"),
        schema="raw",
    )
    op.create_table(
        "raw_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("record_number", sa.Integer(), nullable=False),
        sa.Column("source_record_key", sa.String(255)),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("parsed_ok", sa.Boolean(), nullable=False),
        sa.Column("parse_error", sa.Text()),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("batch_id", "record_number"),
        schema="raw",
    )
    op.create_table(
        "price_bars",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("instrument_code", sa.String(64), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("open", sa.Numeric(18, 6), nullable=False),
        sa.Column("high", sa.Numeric(18, 6), nullable=False),
        sa.Column("low", sa.Numeric(18, 6), nullable=False),
        sa.Column("close", sa.Numeric(18, 6), nullable=False),
        sa.Column("volume", sa.Numeric(24, 6)),
        sa.Column("volume_type", sa.String(32), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_record_key", sa.String(255), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("close_time > open_time", name="ck_price_bar_time_order"),
        sa.CheckConstraint(
            "high >= open AND high >= close AND high >= low AND low <= open AND low <= close",
            name="ck_price_bar_ohlc_geometry",
        ),
        sa.PrimaryKeyConstraint("id", "open_time"),
        sa.UniqueConstraint(
            "provider_code", "instrument_code", "timeframe", "open_time", "available_at"
        ),
        schema="market",
    )
    op.create_index(
        "ix_price_bars_pit",
        "price_bars",
        ["instrument_code", "timeframe", "available_at", "open_time"],
        schema="market",
    )
    op.execute(
        "SELECT create_hypertable('market.price_bars', 'open_time', "
        "if_not_exists => TRUE, migrate_data => TRUE)"
    )
    op.create_table(
        "observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("series_code", sa.String(96), nullable=False),
        sa.Column("value", sa.Numeric(24, 10), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("vintage", sa.String(64), nullable=False),
        sa.Column("is_revision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_record_key", sa.String(255), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id", "observation_time"),
        sa.UniqueConstraint("series_code", "observation_time", "available_at", "vintage"),
        schema="market",
    )
    op.create_index(
        "ix_observations_pit",
        "observations",
        ["series_code", "available_at", "observation_time"],
        schema="market",
    )
    op.execute(
        "SELECT create_hypertable('market.observations', 'observation_time', "
        "if_not_exists => TRUE, migrate_data => TRUE)"
    )
    op.create_table(
        "signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("layer", sa.Integer(), nullable=False),
        sa.Column("driver", sa.String(96), nullable=False),
        sa.Column("epistemic_status", sa.String(16), nullable=False),
        sa.Column("direction", sa.Numeric(8, 6), nullable=False),
        sa.Column("strength", sa.Numeric(6, 3), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 3), nullable=False),
        sa.Column("freshness", sa.Numeric(6, 3), nullable=False),
        sa.Column("data_quality", sa.Numeric(6, 3), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column(
            "contradicting_evidence", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("ruleset_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("direction >= -1 AND direction <= 1", name="ck_signal_direction"),
        sa.CheckConstraint("strength >= 0 AND strength <= 100", name="ck_signal_strength"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_signal_confidence"),
        sa.CheckConstraint("freshness >= 0 AND freshness <= 100", name="ck_signal_freshness"),
        sa.CheckConstraint("data_quality >= 0 AND data_quality <= 100", name="ck_signal_quality"),
        schema="analytics",
    )
    op.create_table(
        "score_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("instrument_code", sa.String(64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("overall_score", sa.Numeric(7, 3), nullable=False),
        sa.Column("bullish_score", sa.Numeric(7, 3), nullable=False),
        sa.Column("bearish_score", sa.Numeric(7, 3), nullable=False),
        sa.Column("neutrality_score", sa.Numeric(7, 3), nullable=False),
        sa.Column("conflict_score", sa.Numeric(7, 3), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 3), nullable=False),
        sa.Column("coverage", sa.Numeric(6, 3), nullable=False),
        sa.Column("bias_label", sa.String(32), nullable=False),
        sa.Column("execution_state", sa.String(32), nullable=False),
        sa.Column("dominant_driver", sa.String(96)),
        sa.Column("main_contradiction", sa.String(128)),
        sa.Column("reasoning", postgresql.JSONB(), nullable=False),
        sa.Column("layers", postgresql.JSONB(), nullable=False),
        sa.Column("signal_ids", postgresql.JSONB(), nullable=False),
        sa.Column("ruleset_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("overall_score >= -100 AND overall_score <= 100", name="ck_score_total"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_score_confidence"),
        sa.CheckConstraint("coverage >= 0 AND coverage <= 100", name="ck_score_coverage"),
        sa.UniqueConstraint("instrument_code", "as_of", "ruleset_version"),
        schema="analytics",
    )
    op.create_table(
        "data_quality_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"),
        ),
        sa.Column("code", sa.String(96), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        schema="ops",
    )
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_key", sa.String(128), nullable=False, unique=True),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error", postgresql.JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="ops",
    )


def downgrade() -> None:
    for table, schema in (
        ("jobs", "ops"),
        ("data_quality_issues", "ops"),
        ("score_snapshots", "analytics"),
        ("signals", "analytics"),
        ("observations", "market"),
        ("price_bars", "market"),
        ("raw_records", "raw"),
        ("ingestion_batches", "raw"),
        ("series", "catalog"),
        ("instruments", "catalog"),
        ("providers", "catalog"),
    ):
        op.drop_table(table, schema=schema)
    for schema in ("ops", "analytics", "market", "raw", "catalog"):
        op.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}"'))
