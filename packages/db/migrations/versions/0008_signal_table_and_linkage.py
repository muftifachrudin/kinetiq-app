"""Add signal table + trade_annotation.signal_id linkage (F0b, docs/sonnet5-implementation-roadmap.md)

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-03

Deliberately deferred until now -- migration 0005's docstring and
shadow_pair.py's module docstring both explicitly said building a `signal`
table with no live writer would be exactly the "design for a hypothetical
future requirement" this codebase's own conventions warn against. That
blocker is resolved: fit_weights.py (Fase 3) and the F7 shadow loop are
real, existing consumers/writers of this schema now.

No RLS / tenant_id on `signal` -- same convention as ohlcv/funding_rate/
open_interest (shared strategy-engine output for one instrument, not
tenant-owned). Not partitioned by ts -- signal volume is trade_annotation-
scale (one row per gated touch-bar), not ohlcv-scale (one row per candle
across every instrument).

signal_id on trade_annotation is nullable: every row logged before this
migration (and for a while after, until F7's live loop exists) has nothing
to link to. shadow_pair.py's heuristic (time+direction) matcher is
unaffected by this migration -- it keeps working exactly as before until a
live writer starts populating signal_id going forward.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE signal (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            instrument_id INTEGER NOT NULL REFERENCES instrument(id),
            timeframe TEXT NOT NULL,
            ts TIMESTAMPTZ NOT NULL,
            direction TEXT NOT NULL,
            entry_price NUMERIC(24, 10) NOT NULL,
            stop_loss NUMERIC(24, 10) NOT NULL,
            take_profit_1 NUMERIC(24, 10),
            confidence NUMERIC(5, 4) NOT NULL,
            factor_scores JSONB,
            created_at TIMESTAMPTZ DEFAULT now(),
            CONSTRAINT ck_signal_direction CHECK (direction IN ('long', 'short')),
            CONSTRAINT uq_signal_instrument_timeframe_ts UNIQUE (instrument_id, timeframe, ts)
        )
        """
    )
    op.execute(
        """
        ALTER TABLE trade_annotation
            ADD COLUMN signal_id BIGINT REFERENCES signal(id)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE trade_annotation
            DROP COLUMN signal_id
        """
    )
    op.execute("DROP TABLE signal")
