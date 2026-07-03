"""Add risk_mandate.default_margin_mode + risk_pct_per_trade (F7a, docs/margin-mode-brief.md Section 5)

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-03

position_sizing.py (F7a, docs/sonnet5-implementation-roadmap.md) needs
these two mandate-level fields to build a PreTradeCard: margin mode is
decided once at onboarding, not re-chosen per trade (brief Section 1 --
letting it vary per-signal would add a hand-tuned degree of freedom and
break shadow-pair comparability across trades), and risk_pct_per_trade is
the mandate's own per-trade risk sizing input.

Originally the roadmap doc (Fase 0d entry) noted these columns would be
"dititipkan" onto the Fase 0d migration PR for a single CODEOWNERS review
pass, since that PR already touched packages/db/migrations/. Fase 0d
(migration 0006) merged and was executed in production before F7a's own
work started, so that opportunistic bundling never happened -- this is a
separate migration instead, same CODEOWNERS review requirement either way.

default_margin_mode allows 'cross' as a valid stored value (onboarding
surfaces it as "coming soon", brief Section 5's table) even though
position_sizing.py itself raises NotImplementedError for cross today --
the mandate schema isn't the place to enforce that MVP scope limitation,
the sizing code is (CrossMarginNotImplementedError in position_sizing.py).

risk_pct_per_trade's hard cap of 2% (brief Section 5: "hard cap 2%") is
deliberately NOT a CHECK constraint here -- brief Section 6 lists any hard
cap as something that must never be loosened by data/ML, which argues for
enforcing it in application code (visible, easily grep-able, easy to unit
test) rather than silently in a constraint an operator could ALTER away
without noticing. server_default 0.01 (1%) matches the brief's onboarding
table's "MVP" column.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE risk_mandate
            ADD COLUMN default_margin_mode TEXT NOT NULL DEFAULT 'isolated',
            ADD COLUMN risk_pct_per_trade NUMERIC(5, 4) NOT NULL DEFAULT 0.01
        """
    )
    op.execute(
        """
        ALTER TABLE risk_mandate
            ADD CONSTRAINT ck_risk_mandate_default_margin_mode
                CHECK (default_margin_mode IN ('cross', 'isolated'))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE risk_mandate
            DROP CONSTRAINT ck_risk_mandate_default_margin_mode
        """
    )
    op.execute(
        """
        ALTER TABLE risk_mandate
            DROP COLUMN default_margin_mode,
            DROP COLUMN risk_pct_per_trade
        """
    )
