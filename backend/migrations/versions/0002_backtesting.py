"""Add durable strategy backtest runs and trades."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_backtesting"
down_revision: str | None = "0001_platform_foundation"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
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
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("equity_curve", postgresql.JSONB(), nullable=False),
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
        "ix_backtest_runs_created",
        "backtest_runs",
        ["created_at"],
        schema="analytics",
    )
    op.create_table(
        "backtest_trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analytics.backtest_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("exit_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("stop_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("target_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("quantity_lots", sa.Numeric(18, 8), nullable=False),
        sa.Column("exit_reason", sa.String(32), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(18, 2), nullable=False),
        sa.Column("costs", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_pnl", sa.Numeric(18, 2), nullable=False),
        sa.Column("r_multiple", sa.Numeric(12, 6), nullable=False),
        sa.Column("mfe_r", sa.Numeric(12, 6), nullable=False),
        sa.Column("mae_r", sa.Numeric(12, 6), nullable=False),
        sa.Column("holding_minutes", sa.Integer(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("run_id", "sequence"),
        schema="analytics",
    )
    op.create_index(
        "ix_backtest_trades_run",
        "backtest_trades",
        ["run_id", "sequence"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_table("backtest_trades", schema="analytics")
    op.drop_table("backtest_runs", schema="analytics")

