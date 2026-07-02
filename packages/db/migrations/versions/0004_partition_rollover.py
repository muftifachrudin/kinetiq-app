"""Partitioning automation (docs/prd.md Section B.9 Fase 1 gap)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-02

Creates kinetiq_ensure_month_partition(p_table, p_month), the function both
this migration and infra/neon/partitioning/rollover.sql call, then uses it
to backfill real rows already sitting in each table's DEFAULT partition
(production has funding_rate/ohlcv data spanning 2026-06-27..2026-07-01 --
neither table has ever had a real time-range partition, everything landed
in DEFAULT since migration 0001).

The function is deliberately idempotent and safe for both cases it's used
for: (1) a month whose rows currently live in DEFAULT (this migration's
job right now) -- Postgres refuses to ATTACH a new range partition while
DEFAULT still holds a row in that range ("would be violated by some row"),
so those rows must be moved out first, not after; (2) a future month with
zero rows anywhere yet (the ongoing rollover job's normal case) -- the same
move step just deletes 0 rows and the partition is created empty, ready
ahead of time.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PARTITIONED_TABLES = [
    "funding_rate",
    "open_interest",
    "price_basis",
    "orderbook_snapshot",
    "liquidation_event",
    "market_sentiment",
    "ohlcv",
]

# Backfill window: covers all data seen in DEFAULT so far (2026-06-27..07-01)
# with a one-month safety margin on each side, plus a few months ahead so
# infra/neon/partitioning/rollover.sql doesn't need to run immediately
# after this migration lands on a fresh deploy.
BACKFILL_MONTHS_BACK = 2
BACKFILL_MONTHS_AHEAD = 3


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION kinetiq_ensure_month_partition(p_table text, p_month date)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE
            v_partition_name text := p_table || '_y' || to_char(p_month, 'YYYY') || 'm' || to_char(p_month, 'MM');
            v_range_start date := date_trunc('month', p_month)::date;
            v_range_end date := (date_trunc('month', p_month) + interval '1 month')::date;
            v_exists boolean;
            v_cols text;
        BEGIN
            SELECT EXISTS (SELECT 1 FROM pg_class WHERE relname = v_partition_name) INTO v_exists;
            IF v_exists THEN
                RETURN;
            END IF;

            EXECUTE format('CREATE TABLE %I (LIKE %I INCLUDING ALL)', v_partition_name, p_table);

            -- Explicit, non-generated column list -- price_basis's
            -- basis/basis_pct are GENERATED ALWAYS (computed from
            -- mark_price/index_price), Postgres rejects INSERT ... SELECT *
            -- writing into those directly ("cannot insert a non-DEFAULT
            -- value into column"). The new partition recomputes them itself
            -- (LIKE ... INCLUDING ALL copied the GENERATED expression too).
            SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position)
            INTO v_cols
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = p_table AND is_generated <> 'ALWAYS';

            -- Move any rows the DEFAULT partition already holds for this
            -- range out of it before attaching -- see module docstring.
            EXECUTE format(
                'WITH moved AS (DELETE FROM %I WHERE ts >= %L AND ts < %L RETURNING *) '
                'INSERT INTO %I (%s) SELECT %s FROM moved',
                p_table, v_range_start, v_range_end, v_partition_name, v_cols, v_cols
            );

            EXECUTE format(
                'ALTER TABLE %I ATTACH PARTITION %I FOR VALUES FROM (%L) TO (%L)',
                p_table, v_partition_name, v_range_start, v_range_end
            );
        END;
        $$
        """
    )

    for table in PARTITIONED_TABLES:
        for offset in range(-BACKFILL_MONTHS_BACK, BACKFILL_MONTHS_AHEAD + 1):
            op.execute(
                f"SELECT kinetiq_ensure_month_partition("
                f"'{table}', (date_trunc('month', CURRENT_DATE) + interval '{offset} month')::date)"
            )


def downgrade() -> None:
    # Move every non-default partition's data back into DEFAULT and drop
    # it, mirroring 0001's original DEFAULT-only layout. Detach BEFORE
    # inserting -- inserting into the parent while the source partition is
    # still attached would just route rows right back into itself (same
    # range), not into DEFAULT.
    for table in PARTITIONED_TABLES:
        op.execute(
            f"""
            DO $$
            DECLARE
                r RECORD;
                v_cols text;
            BEGIN
                SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position)
                INTO v_cols
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = '{table}' AND is_generated <> 'ALWAYS';

                FOR r IN
                    SELECT c.relname
                    FROM pg_inherits i
                    JOIN pg_class c ON c.oid = i.inhrelid
                    WHERE i.inhparent = '{table}'::regclass
                      AND c.relname != '{table}_default'
                LOOP
                    EXECUTE format('ALTER TABLE {table} DETACH PARTITION %I', r.relname);
                    EXECUTE format('INSERT INTO {table} (%s) SELECT %s FROM %I', v_cols, v_cols, r.relname);
                    EXECUTE format('DROP TABLE %I', r.relname);
                END LOOP;
            END $$
            """
        )
    op.execute("DROP FUNCTION kinetiq_ensure_month_partition(text, date)")
