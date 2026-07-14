"""Add running-PnL columns to position + new equity_snapshot table

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-14

Per docs/daily-loss-limit-exposure-cap-brief.md: `position` previously had
no explicit open/closed status (only inferred from `closed_at IS NULL`,
a fragile convention) and no `exit_price` at all -- so realized PnL was
literally uncomputable even after the fact. This migration is schema-only:
it does NOT wire anything into `execution/risk_gate.py` or build the
orchestration layer that would actually populate these columns from real
fills (that layer -- `execution/custody/`, `agent-orchestrator/graphs/` --
still doesn't exist). It only lays the foundation the brief's daily-loss-
limit/drawdown-kill-switch formulas need once that orchestration exists.

`status` backfills existing rows from the old `closed_at IS NULL`
convention before being made NOT NULL, so this is safe against any rows
already present (in practice the table is empty -- no live execution has
ever run -- but this doesn't assume that).

`equity_snapshot` is a new, separate ledger table (composite PK
`(account_id, ts)`, no surrogate id -- same time-series convention as
`funding_rate`/`ohlcv`/`onchain_exchange_flow`) rather than trying to
recompute "equity at start of today" / "peak equity ever" from raw
position history on every gate check -- a periodic snapshot is cheaper
and matches the brief's own reasoning (Section 2).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE position ADD COLUMN status TEXT")
    op.execute("UPDATE position SET status = CASE WHEN closed_at IS NULL THEN 'open' ELSE 'closed' END")
    op.execute("ALTER TABLE position ALTER COLUMN status SET NOT NULL")
    op.execute("ALTER TABLE position ADD CONSTRAINT ck_position_status CHECK (status in ('open', 'closed'))")
    op.execute("ALTER TABLE position ADD COLUMN exit_price NUMERIC(24,10)")
    op.execute("ALTER TABLE position ADD COLUMN realized_pnl_usd NUMERIC(24,4)")

    op.execute(
        """
        CREATE TABLE equity_snapshot (
            account_id INT NOT NULL,
            ts TIMESTAMPTZ NOT NULL,
            equity_usd NUMERIC(24,4) NOT NULL,
            realized_pnl_usd NUMERIC(24,4),
            unrealized_pnl_usd NUMERIC(24,4),
            PRIMARY KEY (account_id, ts)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS equity_snapshot")
    op.execute("ALTER TABLE position DROP COLUMN IF EXISTS realized_pnl_usd")
    op.execute("ALTER TABLE position DROP COLUMN IF EXISTS exit_price")
    op.execute("ALTER TABLE position DROP CONSTRAINT IF EXISTS ck_position_status")
    op.execute("ALTER TABLE position DROP COLUMN IF EXISTS status")
