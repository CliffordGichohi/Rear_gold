"""Add encrypted provider OAuth connection storage and audit events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_ctrader_oauth"
down_revision: str | None = "0004_event_research"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_oauth_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_code", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("token_type", sa.String(16), nullable=False),
        sa.Column("encryption_version", sa.String(16), nullable=False),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=False),
        sa.Column(
            "access_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('AUTHORIZED', 'EXPIRED', 'REVOKED')",
            name="ck_provider_oauth_connection_status",
        ),
        sa.UniqueConstraint(
            "provider_code",
            "environment",
            name="uq_provider_oauth_connection",
        ),
        schema="ops",
    )
    op.create_index(
        "ix_provider_oauth_connections_status",
        "provider_oauth_connections",
        ["provider_code", "environment", "status"],
        schema="ops",
    )
    op.create_table(
        "provider_oauth_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "ops.provider_oauth_connections.id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="ops",
    )
    op.create_index(
        "ix_provider_oauth_audit_events_connection_time",
        "provider_oauth_audit_events",
        ["connection_id", "occurred_at"],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_table("provider_oauth_audit_events", schema="ops")
    op.drop_table("provider_oauth_connections", schema="ops")
