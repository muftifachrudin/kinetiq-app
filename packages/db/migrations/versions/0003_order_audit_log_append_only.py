"""Make order_audit_log genuinely append-only (docs/prd.md Section B.7)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-01

A plain `REVOKE UPDATE, DELETE ON order_audit_log FROM <role>` would not
actually protect anything today: Postgres object owners always retain full
privileges on objects they own regardless of any GRANT/REVOKE, and the app's
`DATABASE_URL` role currently owns this table (same situation that required
`FORCE ROW LEVEL SECURITY` in 0002 -- owners are exempt from privilege
checks the same way they're exempt from RLS unless forced). REVOKE has no
equivalent "FORCE" escape hatch, so it would be a silent no-op against the
app's own connection.

A `BEFORE UPDATE OR DELETE` trigger enforces unconditionally, regardless of
role or ownership -- there is no bypass, including for a future superadmin
session or a role-separation project done later. This is deliberate: an
audit trail that could be edited by *any* role (even the most trusted one)
via the normal app path isn't actually an audit trail. Corrections belong in
new compensating rows, not edits to history. A genuine emergency fix (there
should be no ordinary reason for one) is an explicit, deliberate, separately
auditable DBA action (`ALTER TABLE order_audit_log DISABLE TRIGGER ...`), not
something any session variable or app code path can quietly opt out of.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_order_audit_log_mutation() RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'order_audit_log is append-only: % is not allowed', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER order_audit_log_append_only
        BEFORE UPDATE OR DELETE ON order_audit_log
        FOR EACH ROW EXECUTE FUNCTION reject_order_audit_log_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER order_audit_log_append_only ON order_audit_log")
    op.execute("DROP FUNCTION reject_order_audit_log_mutation()")
