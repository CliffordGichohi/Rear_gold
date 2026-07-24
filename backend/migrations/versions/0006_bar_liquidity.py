"""Persist observed broker spread carried by historical price bars."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_bar_liquidity"
down_revision: str | None = "0005_ctrader_oauth"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_bars",
        sa.Column("spread_points", sa.Integer()),
        schema="market",
    )
    op.add_column(
        "price_bars",
        sa.Column("spread_price", sa.Numeric(18, 8)),
        schema="market",
    )
    op.create_check_constraint(
        "ck_price_bar_spread_points",
        "price_bars",
        "spread_points IS NULL OR spread_points >= 0",
        schema="market",
    )
    op.create_check_constraint(
        "ck_price_bar_spread_price",
        "price_bars",
        "spread_price IS NULL OR spread_price >= 0",
        schema="market",
    )
    op.create_index(
        "ix_raw_records_batch_source_key",
        "raw_records",
        ["batch_id", "source_record_key"],
        schema="raw",
    )

    # The original MT5 CSV rows were already retained immutably in raw_records.
    # Enrich the normalized projection from those facts rather than re-downloading
    # or mutating raw history. IC Markets KE XAUUSD was validated at two decimals
    # with SYMBOL_POINT=0.01 on terminal build 5833.
    op.execute(
        sa.text(
            """
            UPDATE market.price_bars AS bar
            SET
                spread_points = (record.payload ->> 'spread_points')::integer,
                spread_price = (
                    (record.payload ->> 'spread_points')::numeric * 0.01
                )
            FROM raw.raw_records AS record
            WHERE
                record.batch_id = bar.batch_id
                AND record.source_record_key = bar.source_record_key
                AND record.parsed_ok = TRUE
                AND bar.provider_code = 'IC_MARKETS_MT5'
                AND bar.instrument_code = 'XAUUSD'
                AND record.payload ->> 'spread_points' ~ '^[0-9]+$'
                AND bar.spread_points IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_raw_records_batch_source_key",
        table_name="raw_records",
        schema="raw",
    )
    op.drop_constraint(
        "ck_price_bar_spread_price",
        "price_bars",
        schema="market",
        type_="check",
    )
    op.drop_constraint(
        "ck_price_bar_spread_points",
        "price_bars",
        schema="market",
        type_="check",
    )
    op.drop_column("price_bars", "spread_price", schema="market")
    op.drop_column("price_bars", "spread_points", schema="market")
