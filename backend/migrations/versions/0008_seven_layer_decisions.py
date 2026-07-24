"""Persist auditable seven-layer decisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_seven_layer_decisions"
down_revision: str | None = "0007_policy_expectation_windows"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("instrument_code", sa.String(64), nullable=False),
        sa.Column("provider_code", sa.String(64)),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("epistemic_status", sa.String(16), nullable=False),
        sa.Column("directional_score", sa.Numeric(7, 3), nullable=False),
        sa.Column("bullish_score", sa.Numeric(7, 3), nullable=False),
        sa.Column("bearish_score", sa.Numeric(7, 3), nullable=False),
        sa.Column("neutral_conflict_score", sa.Numeric(7, 3), nullable=False),
        sa.Column("directional_confidence", sa.Numeric(6, 3), nullable=False),
        sa.Column("execution_confidence", sa.Numeric(6, 3), nullable=False),
        sa.Column(
            "directional_evidence_coverage_pct",
            sa.Numeric(6, 3),
            nullable=False,
        ),
        sa.Column("phase1_factor_coverage_pct", sa.Numeric(6, 3), nullable=False),
        sa.Column("book_factor_coverage_pct", sa.Numeric(6, 3), nullable=False),
        sa.Column("book_usable_coverage_pct", sa.Numeric(6, 3), nullable=False),
        sa.Column("bias_label", sa.String(32), nullable=False),
        sa.Column("regime_label", sa.String(64), nullable=False),
        sa.Column("reaction_function", sa.String(64), nullable=False),
        sa.Column("dominant_driver", sa.String(96)),
        sa.Column("main_contradiction", sa.Text()),
        sa.Column("highest_risk_assumption", sa.Text(), nullable=False),
        sa.Column("upcoming_catalyst", postgresql.JSONB()),
        sa.Column("event_risk", sa.String(24), nullable=False),
        sa.Column("current_session", sa.String(64), nullable=False),
        sa.Column("liquidity_state", sa.String(24), nullable=False),
        sa.Column("price_macro_alignment", sa.String(24), nullable=False),
        sa.Column("execution_state", sa.String(64), nullable=False),
        sa.Column("layers", postgresql.JSONB(), nullable=False),
        sa.Column("components", postgresql.JSONB(), nullable=False),
        sa.Column("execution_plan", postgresql.JSONB(), nullable=False),
        sa.Column("reasoning", postgresql.JSONB(), nullable=False),
        sa.Column(
            "fundamental_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analytics.fundamental_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("fundamental_data_hash", sa.String(64), nullable=False),
        sa.Column("structure_data_hash", sa.String(64)),
        sa.Column("registry_hash", sa.String(64), nullable=False),
        sa.Column("data_hash", sa.String(64), nullable=False),
        sa.Column("ruleset_version", sa.String(96), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "directional_score >= -100 AND directional_score <= 100",
            name="ck_decision_directional_score",
        ),
        sa.CheckConstraint(
            "bullish_score >= 0 AND bullish_score <= 100",
            name="ck_decision_bullish_score",
        ),
        sa.CheckConstraint(
            "bearish_score >= 0 AND bearish_score <= 100",
            name="ck_decision_bearish_score",
        ),
        sa.CheckConstraint(
            "neutral_conflict_score >= 0 AND neutral_conflict_score <= 100",
            name="ck_decision_neutral_conflict_score",
        ),
        sa.CheckConstraint(
            "directional_confidence >= 0 AND directional_confidence <= 100",
            name="ck_decision_directional_confidence",
        ),
        sa.CheckConstraint(
            "execution_confidence >= 0 AND execution_confidence <= 100",
            name="ck_decision_execution_confidence",
        ),
        sa.CheckConstraint(
            "directional_evidence_coverage_pct >= 0 "
            "AND directional_evidence_coverage_pct <= 100",
            name="ck_decision_directional_coverage",
        ),
        sa.CheckConstraint(
            "phase1_factor_coverage_pct >= 0 AND phase1_factor_coverage_pct <= 100",
            name="ck_decision_phase1_coverage",
        ),
        sa.CheckConstraint(
            "book_factor_coverage_pct >= 0 AND book_factor_coverage_pct <= 100",
            name="ck_decision_book_coverage",
        ),
        sa.CheckConstraint(
            "book_usable_coverage_pct >= 0 AND book_usable_coverage_pct <= 100",
            name="ck_decision_book_usable_coverage",
        ),
        sa.UniqueConstraint(
            "instrument_code",
            "as_of",
            "ruleset_version",
            "data_hash",
            name="uq_decision_snapshot_evidence",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_decision_snapshots_latest",
        "decision_snapshots",
        ["instrument_code", "as_of", "created_at"],
        schema="analytics",
    )
    op.create_index(
        "ix_decision_snapshots_evidence",
        "decision_snapshots",
        ["fundamental_data_hash", "structure_data_hash", "registry_hash"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_table("decision_snapshots", schema="analytics")
