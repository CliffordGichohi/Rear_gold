"""Add event provenance, surprise analytics, and reaction studies."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_event_research"
down_revision: str | None = "0003_fundamental_domain"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    for table in (
        "economic_events",
        "forecast_snapshots",
        "economic_releases",
        "policy_path_points",
    ):
        op.add_column(
            table,
            sa.Column(
                "is_synthetic",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            schema="market",
        )
    op.add_column(
        "economic_releases",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True)),
        schema="market",
    )
    op.create_foreign_key(
        "fk_economic_releases_batch",
        "economic_releases",
        "ingestion_batches",
        ["batch_id"],
        ["id"],
        source_schema="market",
        referent_schema="raw",
        ondelete="RESTRICT",
    )
    op.add_column(
        "fundamental_snapshots",
        sa.Column(
            "event_risk",
            sa.String(16),
            nullable=False,
            server_default="UNKNOWN",
        ),
        schema="analytics",
    )
    op.add_column(
        "fundamental_snapshots",
        sa.Column("upcoming_catalyst", postgresql.JSONB()),
        schema="analytics",
    )

    op.create_table(
        "economic_surprises",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market.economic_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "release_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market.economic_releases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "forecast_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market.forecast_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("component_code", sa.String(96), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_surprise", sa.Numeric(24, 10), nullable=False),
        sa.Column("standardized_surprise", sa.Numeric(12, 8), nullable=False),
        sa.Column("gold_direction", sa.Numeric(8, 6), nullable=False),
        sa.Column("strength", sa.Numeric(6, 3), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 3), nullable=False),
        sa.Column("history_count", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("epistemic_status", sa.String(16), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("ruleset_version", sa.String(64), nullable=False),
        sa.Column("data_hash", sa.String(64), nullable=False),
        sa.Column(
            "is_synthetic",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "gold_direction >= -1 AND gold_direction <= 1",
            name="ck_surprise_gold_direction",
        ),
        sa.CheckConstraint(
            "strength >= 0 AND strength <= 100",
            name="ck_surprise_strength",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_surprise_confidence",
        ),
        sa.UniqueConstraint(
            "release_id",
            "forecast_id",
            "ruleset_version",
            "data_hash",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_economic_surprises_pit",
        "economic_surprises",
        ["component_code", "available_at", "released_at"],
        schema="analytics",
    )

    op.create_table(
        "event_reactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market.economic_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "release_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market.economic_releases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "surprise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analytics.economic_surprises.id", ondelete="RESTRICT"),
        ),
        sa.Column("instrument_code", sa.String(64), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("horizon_code", sa.String(24), nullable=False),
        sa.Column("reference_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("horizon_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("price_change", sa.Numeric(18, 6), nullable=False),
        sa.Column("return_pct", sa.Numeric(16, 8), nullable=False),
        sa.Column("mfe_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("mae_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("first_move_direction", sa.String(8), nullable=False),
        sa.Column("first_move_held", sa.Boolean()),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculation_version", sa.String(64), nullable=False),
        sa.Column("data_hash", sa.String(64), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column(
            "is_synthetic",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "release_id",
            "instrument_code",
            "provider_code",
            "horizon_code",
            "calculation_version",
            "data_hash",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_event_reactions_release_horizon",
        "event_reactions",
        ["release_id", "horizon_code", "available_at"],
        schema="analytics",
    )

    op.create_table(
        "event_study_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("instrument_code", sa.String(64), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("data_hash", sa.String(64), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("exclusions", postgresql.JSONB(), nullable=False),
        sa.Column("results", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        schema="analytics",
    )
    op.create_index(
        "ix_event_study_runs_created",
        "event_study_runs",
        ["created_at"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_table("event_study_runs", schema="analytics")
    op.drop_table("event_reactions", schema="analytics")
    op.drop_table("economic_surprises", schema="analytics")
    op.drop_column("fundamental_snapshots", "upcoming_catalyst", schema="analytics")
    op.drop_column("fundamental_snapshots", "event_risk", schema="analytics")
    op.drop_constraint(
        "fk_economic_releases_batch",
        "economic_releases",
        schema="market",
        type_="foreignkey",
    )
    op.drop_column("economic_releases", "batch_id", schema="market")
    for table in (
        "policy_path_points",
        "economic_releases",
        "forecast_snapshots",
        "economic_events",
    ):
        op.drop_column(table, "is_synthetic", schema="market")
