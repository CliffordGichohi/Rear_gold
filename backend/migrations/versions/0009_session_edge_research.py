"""Persist fundamental-biased session and liquidity edge studies."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_session_edge_research"
down_revision: str | None = "0008_seven_layer_decisions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_edge_study_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("strategy_name", sa.String(128), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("instrument_code", sa.String(64), nullable=False),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("data_hash", sa.String(64), nullable=False),
        sa.Column("source_bar_count", sa.Integer(), nullable=False),
        sa.Column("session_count", sa.Integer(), nullable=False),
        sa.Column("trigger_count", sa.Integer(), nullable=False),
        sa.Column("results", postgresql.JSONB(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
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
        "ix_session_edge_runs_latest",
        "session_edge_study_runs",
        ["instrument_code", "provider_code", "created_at"],
        schema="analytics",
    )
    op.create_index(
        "ix_session_edge_runs_period",
        "session_edge_study_runs",
        ["start_time", "end_time", "strategy_version"],
        schema="analytics",
    )

    op.create_table(
        "session_opportunities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "analytics.session_edge_study_runs.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column(
            "fundamental_freeze_time",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("level_freeze_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("london_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("london_end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("no_trigger_reason", sa.String(96)),
        sa.Column("setup_side", sa.String(8)),
        sa.Column("signal_time", sa.DateTime(timezone=True)),
        sa.Column("entry_time", sa.DateTime(timezone=True)),
        sa.Column("bias_alignment", sa.String(40), nullable=False),
        sa.Column("directional_score", sa.Numeric(7, 3)),
        sa.Column("fundamental_confidence", sa.Numeric(6, 3)),
        sa.Column("fundamental_coverage", sa.Numeric(6, 3)),
        sa.Column("regime_label", sa.String(64), nullable=False),
        sa.Column("dominant_driver", sa.String(96)),
        sa.Column("event_risk", sa.String(24), nullable=False),
        sa.Column("asia_high", sa.Numeric(18, 6)),
        sa.Column("asia_low", sa.Numeric(18, 6)),
        sa.Column("asia_range_size", sa.Numeric(18, 6)),
        sa.Column("asia_range_percentile", sa.Numeric(7, 3)),
        sa.Column("asia_compression_state", sa.String(24), nullable=False),
        sa.Column("entry_reference_price", sa.Numeric(18, 6)),
        sa.Column("invalidation_price", sa.Numeric(18, 6)),
        sa.Column("risk_distance", sa.Numeric(18, 6)),
        sa.Column("facts", postgresql.JSONB(), nullable=False),
        sa.Column("outcomes", postgresql.JSONB(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("data_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "directional_score IS NULL OR (directional_score >= -100 AND directional_score <= 100)",
            name="ck_session_opportunity_directional_score",
        ),
        sa.CheckConstraint(
            "fundamental_confidence IS NULL OR "
            "(fundamental_confidence >= 0 AND fundamental_confidence <= 100)",
            name="ck_session_opportunity_fundamental_confidence",
        ),
        sa.CheckConstraint(
            "fundamental_coverage IS NULL OR "
            "(fundamental_coverage >= 0 AND fundamental_coverage <= 100)",
            name="ck_session_opportunity_fundamental_coverage",
        ),
        sa.CheckConstraint(
            "asia_range_percentile IS NULL OR "
            "(asia_range_percentile >= 0 AND asia_range_percentile <= 100)",
            name="ck_session_opportunity_asia_percentile",
        ),
        sa.UniqueConstraint(
            "run_id",
            "session_date",
            name="uq_session_opportunity_run_date",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_session_opportunities_run_date",
        "session_opportunities",
        ["run_id", "session_date"],
        schema="analytics",
    )
    op.create_index(
        "ix_session_opportunities_cohort",
        "session_opportunities",
        [
            "setup_side",
            "bias_alignment",
            "event_risk",
            "asia_compression_state",
        ],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_table("session_opportunities", schema="analytics")
    op.drop_table("session_edge_study_runs", schema="analytics")
