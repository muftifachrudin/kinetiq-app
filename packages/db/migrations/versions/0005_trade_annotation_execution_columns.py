"""Extend trade_annotation with real execution data (docs/shadow-simulator-brief.md Option 2)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-03

Companion to trade_simulator.py's leverage/liquidation-aware simulation
(fib-gann-validation-brief.md Section 13): once the founder starts logging
real trades here, these columns are the "real" side of a future
shadow_pair (sim vs real divergence, brief Section 3-4 -- not built yet,
this migration is ONLY the schema extension, step 2 of the brief's
implementation order).

All new columns are nullable -- the brief is explicit that a signal
without a real trade behind it stays annotated with the real-side columns
empty, and that's still valid data for confluence-weight calibration, not
an incomplete/invalid row. No signal_id linkage column is added here: that
pairing step is the brief's shadow_pair work (a later round), not this
schema-extension step.

fees_paid/funding_paid are named fees_paid_usd/funding_paid_usd here
(deviating from the brief's literal names) to match this schema's own
existing convention for dollar amounts (RiskMandate.max_position_notional_
usd, max_daily_loss_usd) and to avoid ambiguity with trade_simulator.py's
percent-of-notional fee/funding fractions, which this table does not use --
a human fills this in directly from their exchange's real trade history,
in dollars.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE trade_annotation
            ADD COLUMN leverage NUMERIC(6, 3),
            ADD COLUMN margin_mode TEXT,
            ADD COLUMN entry_fill_price NUMERIC(24, 10),
            ADD COLUMN exit_fill_price NUMERIC(24, 10),
            ADD COLUMN fees_paid_usd NUMERIC(24, 4),
            ADD COLUMN funding_paid_usd NUMERIC(24, 4),
            ADD COLUMN exit_reason_real TEXT
        """
    )
    op.execute(
        """
        ALTER TABLE trade_annotation
            ADD CONSTRAINT ck_trade_annotation_margin_mode
                CHECK (margin_mode IN ('cross', 'isolated')),
            ADD CONSTRAINT ck_trade_annotation_exit_reason_real
                CHECK (exit_reason_real IN ('stop_loss', 'take_profit', 'liquidated', 'timeout', 'manual_override'))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE trade_annotation
            DROP CONSTRAINT ck_trade_annotation_margin_mode,
            DROP CONSTRAINT ck_trade_annotation_exit_reason_real
        """
    )
    op.execute(
        """
        ALTER TABLE trade_annotation
            DROP COLUMN leverage,
            DROP COLUMN margin_mode,
            DROP COLUMN entry_fill_price,
            DROP COLUMN exit_fill_price,
            DROP COLUMN fees_paid_usd,
            DROP COLUMN funding_paid_usd,
            DROP COLUMN exit_reason_real
        """
    )
