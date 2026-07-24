"""Add point-in-time events, expectations, positioning, and fundamental snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_fundamental_domain"
down_revision: str | None = "0002_backtesting"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "economic_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_code", sa.String(96), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("is_scheduled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("source_event_key", sa.String(255), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "importance >= 1 AND importance <= 5", name="ck_event_importance"
        ),
        sa.UniqueConstraint("provider_code", "source_event_key", "available_at"),
        schema="market",
    )
    op.create_index(
        "ix_economic_events_pit",
        "economic_events",
        ["event_code", "available_at", "scheduled_at"],
        schema="market",
    )

    op.create_table(
        "forecast_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_code", sa.String(96), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("component_code", sa.String(96), nullable=False),
        sa.Column("forecast_value", sa.Numeric(24, 10), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("forecast_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("vintage", sa.String(64), nullable=False),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "event_code",
            "scheduled_at",
            "component_code",
            "provider_code",
            "available_at",
            "vintage",
        ),
        schema="market",
    )
    op.create_index(
        "ix_forecast_snapshots_pit",
        "forecast_snapshots",
        ["event_code", "scheduled_at", "available_at"],
        schema="market",
    )

    op.create_table(
        "economic_releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market.economic_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("component_code", sa.String(96), nullable=False),
        sa.Column("observation_period", sa.Date(), nullable=False),
        sa.Column("actual_value", sa.Numeric(24, 10), nullable=False),
        sa.Column("previous_value", sa.Numeric(24, 10)),
        sa.Column("revised_previous_value", sa.Numeric(24, 10)),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_revision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vintage", sa.String(64), nullable=False),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("event_id", "component_code", "available_at", "vintage"),
        schema="market",
    )
    op.create_index(
        "ix_economic_releases_pit",
        "economic_releases",
        ["component_code", "available_at", "observation_period"],
        schema="market",
    )

    op.create_table(
        "policy_path_points",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("snapshot_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meeting_date", sa.Date(), nullable=False),
        sa.Column("outcome_basis_points", sa.Integer(), nullable=False),
        sa.Column("probability", sa.Numeric(12, 10), nullable=False),
        sa.Column("expected_rate", sa.Numeric(12, 8)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_record_key", sa.String(255), nullable=False),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "probability >= 0 AND probability <= 1",
            name="ck_policy_path_probability",
        ),
        sa.UniqueConstraint(
            "provider_code",
            "snapshot_as_of",
            "meeting_date",
            "outcome_basis_points",
            "available_at",
        ),
        schema="market",
    )
    op.create_index(
        "ix_policy_path_points_pit",
        "policy_path_points",
        ["available_at", "snapshot_as_of", "meeting_date"],
        schema="market",
    )

    op.create_table(
        "cot_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("report_type", sa.String(64), nullable=False),
        sa.Column("contract_market_code", sa.String(32), nullable=False),
        sa.Column("market_name", sa.String(255), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("publication_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_interest", sa.Integer(), nullable=False),
        sa.Column("source_record_key", sa.String(255), nullable=False),
        sa.Column("availability_quality", sa.String(32), nullable=False),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "publication_at > observation_date",
            name="ck_cot_publication_after_observation",
        ),
        sa.UniqueConstraint(
            "provider_code",
            "report_type",
            "contract_market_code",
            "observation_date",
            "publication_at",
        ),
        schema="market",
    )
    op.create_index(
        "ix_cot_reports_pit",
        "cot_reports",
        ["contract_market_code", "publication_at", "observation_date"],
        schema="market",
    )

    op.create_table(
        "cot_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market.cot_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("long_contracts", sa.Integer(), nullable=False),
        sa.Column("short_contracts", sa.Integer(), nullable=False),
        sa.Column("spreading_contracts", sa.Integer()),
        sa.Column("percent_open_interest_long", sa.Numeric(8, 4)),
        sa.Column("percent_open_interest_short", sa.Numeric(8, 4)),
        sa.Column("traders_long", sa.Integer()),
        sa.Column("traders_short", sa.Integer()),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.CheckConstraint("long_contracts >= 0", name="ck_cot_long_nonnegative"),
        sa.CheckConstraint("short_contracts >= 0", name="ck_cot_short_nonnegative"),
        sa.UniqueConstraint("report_id", "category"),
        schema="market",
    )

    op.create_table(
        "positioning_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("instrument_code", sa.String(64), nullable=False),
        sa.Column("metric_code", sa.String(96), nullable=False),
        sa.Column("observation_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(24, 10), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("vintage", sa.String(64), nullable=False),
        sa.Column("epistemic_status", sa.String(16), nullable=False),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "instrument_code",
            "metric_code",
            "observation_time",
            "available_at",
            "provider_code",
            "vintage",
        ),
        schema="market",
    )
    op.create_index(
        "ix_positioning_observations_pit",
        "positioning_observations",
        ["instrument_code", "metric_code", "available_at", "observation_time"],
        schema="market",
    )

    op.create_table(
        "fundamental_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("instrument_code", sa.String(64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("directional_score", sa.Numeric(7, 3), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 3), nullable=False),
        sa.Column("coverage", sa.Numeric(6, 3), nullable=False),
        sa.Column("bias_label", sa.String(32), nullable=False),
        sa.Column("regime_label", sa.String(64), nullable=False),
        sa.Column("reaction_function", sa.String(64), nullable=False),
        sa.Column("dominant_driver", sa.String(96)),
        sa.Column("main_contradiction", sa.Text()),
        sa.Column("components", postgresql.JSONB(), nullable=False),
        sa.Column("layers", postgresql.JSONB(), nullable=False),
        sa.Column("reasoning", postgresql.JSONB(), nullable=False),
        sa.Column("registry_hash", sa.String(64), nullable=False),
        sa.Column("data_hash", sa.String(64), nullable=False),
        sa.Column("ruleset_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "directional_score >= -100 AND directional_score <= 100",
            name="ck_fundamental_score",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_fundamental_confidence",
        ),
        sa.CheckConstraint(
            "coverage >= 0 AND coverage <= 100",
            name="ck_fundamental_coverage",
        ),
        sa.UniqueConstraint(
            "instrument_code", "as_of", "ruleset_version", "data_hash"
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_fundamental_snapshots_pit",
        "fundamental_snapshots",
        ["instrument_code", "as_of", "ruleset_version"],
        schema="analytics",
    )


def downgrade() -> None:
    for table, schema in (
        ("fundamental_snapshots", "analytics"),
        ("positioning_observations", "market"),
        ("cot_positions", "market"),
        ("cot_reports", "market"),
        ("policy_path_points", "market"),
        ("economic_releases", "market"),
        ("forecast_snapshots", "market"),
        ("economic_events", "market"),
    ):
        op.drop_table(table, schema=schema)
