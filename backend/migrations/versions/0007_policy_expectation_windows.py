"""Add quarterly market-implied policy expectation distributions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_policy_expectation_windows"
down_revision: str | None = "0006_bar_liquidity"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_expectation_windows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("snapshot_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference_start", sa.Date(), nullable=False),
        sa.Column("reference_end", sa.Date(), nullable=False),
        sa.Column("target_lower_basis_points", sa.Integer(), nullable=False),
        sa.Column("target_upper_basis_points", sa.Integer(), nullable=False),
        sa.Column("rate_p25_basis_points", sa.Numeric(14, 6), nullable=False),
        sa.Column("rate_mean_basis_points", sa.Numeric(14, 6), nullable=False),
        sa.Column("rate_mode_basis_points", sa.Numeric(14, 6), nullable=False),
        sa.Column("rate_p75_basis_points", sa.Numeric(14, 6), nullable=False),
        sa.Column("probability_cut", sa.Numeric(12, 10)),
        sa.Column("probability_hike", sa.Numeric(12, 10)),
        sa.Column(
            "probability_bins",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("distribution_probability_sum", sa.Numeric(12, 10)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("availability_quality", sa.String(64), nullable=False),
        sa.Column("source_record_key", sa.String(255), nullable=False),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw.ingestion_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "is_synthetic",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "reference_end >= reference_start",
            name="ck_policy_expectation_reference_order",
        ),
        sa.CheckConstraint(
            "available_at > snapshot_as_of",
            name="ck_policy_expectation_availability_order",
        ),
        sa.CheckConstraint(
            "target_upper_basis_points >= target_lower_basis_points",
            name="ck_policy_expectation_target_range",
        ),
        sa.CheckConstraint(
            "probability_cut IS NULL OR "
            "(probability_cut >= 0 AND probability_cut <= 1)",
            name="ck_policy_expectation_cut_probability",
        ),
        sa.CheckConstraint(
            "probability_hike IS NULL OR "
            "(probability_hike >= 0 AND probability_hike <= 1)",
            name="ck_policy_expectation_hike_probability",
        ),
        sa.CheckConstraint(
            "distribution_probability_sum IS NULL OR "
            "(distribution_probability_sum >= 0 AND distribution_probability_sum <= 1.01)",
            name="ck_policy_expectation_probability_sum",
        ),
        sa.UniqueConstraint(
            "provider_code",
            "observation_date",
            "reference_start",
            "available_at",
        ),
        schema="market",
    )
    op.create_index(
        "ix_policy_expectation_windows_pit",
        "policy_expectation_windows",
        ["available_at", "snapshot_as_of", "reference_start"],
        schema="market",
    )
    op.create_index(
        "ix_policy_expectation_windows_observation",
        "policy_expectation_windows",
        ["provider_code", "observation_date", "reference_start"],
        schema="market",
    )


def downgrade() -> None:
    op.drop_table("policy_expectation_windows", schema="market")
