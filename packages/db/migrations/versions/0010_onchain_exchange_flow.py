"""Add onchain_exchange_flow table (Arkham entity flow, collect-only)

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-13

New on-chain intel data source (Arkham Intel API, GET /flow/entity/{entity}):
USD in/outflow of BTC between a tracked entity (e.g. a CEX like "binance")
and the rest of the chain, per time bucket. Deliberately COLLECT-ONLY for
now -- this table has no FK into `instrument`/`venue` and is not wired into
`signal`/confidence scoring anywhere. Per docs/prd.md's "gate keras vs
faktor skor" principle and the `ConfluenceWeights` anti-predictive lesson
(CLAUDE.md), a brand new hand-picked data source doesn't get to influence
a trading decision before it's actually validated via the same walk-forward
discipline every other factor went through -- this migration only adds
storage.

Not partitioned by `ts` (unlike ohlcv/funding_rate/etc): volume here is a
handful of tracked entities x one row per data point from Arkham, not one
row per candle across every instrument -- same unpartitioned-scale
reasoning already used for `signal`/`trade_annotation`.

`source` column (default 'arkham') exists so a second on-chain intel
vendor could reuse this table later without a rename, same reasoning as
`credential.credential_type` being an open enum rather than one table per
credential kind.

Composite primary key (source, entity, chain, ts) -- no surrogate `id` --
matching this repo's existing time-series convention (funding_rate,
ohlcv, open_interest all use their natural key as PK directly). This is
what makes `db.merge()` an idempotent upsert in ingest_onchain.py, same
as every other ingest_*() function in ingest.py: SQLAlchemy's merge()
matches on primary key columns, so it only works here if the natural key
IS the primary key, not a separate unique constraint alongside a
surrogate id.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE onchain_exchange_flow (
            source TEXT NOT NULL DEFAULT 'arkham',
            entity TEXT NOT NULL,
            chain TEXT NOT NULL,
            ts TIMESTAMPTZ NOT NULL,
            inflow_usd NUMERIC(24,4),
            outflow_usd NUMERIC(24,4),
            cumulative_inflow_usd NUMERIC(24,4),
            cumulative_outflow_usd NUMERIC(24,4),
            created_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (source, entity, chain, ts)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS onchain_exchange_flow")
