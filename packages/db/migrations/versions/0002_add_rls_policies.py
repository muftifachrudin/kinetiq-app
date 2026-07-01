"""Add Row-Level Security policies for tenant isolation (docs/prd.md Section B.4)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-01

FORCE ROW LEVEL SECURITY is used (not just ENABLE): the app's runtime
DATABASE_URL currently connects as the same Postgres role that owns these
tables (no separate least-privilege app role exists yet), and Postgres
exempts a table's owner from RLS entirely unless FORCE is also set -- without
it, RLS would be enabled but provide zero actual isolation for this app's own
queries. FORCE only affects DML (SELECT/INSERT/UPDATE/DELETE); migrations are
DDL and are unaffected. Manual psql inserts/updates against these tables
(e.g. bootstrapping the first superadmin/tenant rows) must run
`SET app.is_superadmin = 'true';` first in the same session, or they will be
rejected by the policy's WITH CHECK clause.

`platform_user` is intentionally NOT included here even though it has a
tenant_id column: `api-gateway/deps.py` looks a caller up by `clerk_user_id`
*before* any tenant_id is known (that's how it discovers which tenant the
caller belongs to in the first place), so scoping that lookup by tenant_id
would break login for every user on every request. It's an identity/session
table, not a "tabel domain" in the Section B.4 sense.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables where tenant_id strictly identifies ownership: a row is visible only
# to its own tenant's session, or a superadmin session.
_STRICT_TENANT_TABLES = (
    "tenant_token_ledger",
    "strategy",
    "portfolio_target",
    "position",
    "order_audit_log",
    "risk_mandate",
    "tenant_credential",
    "dlmm_position",
    "trade_annotation",
)

_BYPASS = "current_setting('app.is_superadmin', true) = 'true'"
# NULLIF(..., '') guards against casting '' to uuid: a custom GUC that was
# never set *in this session* can read back as '' rather than NULL once
# Postgres has seen the "app.*" namespace used by any session on the server
# (a well-known quirk of custom placeholder GUCs) -- both '' and a genuine
# NULL must mean "no tenant context", not a cast error.
_TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    for table in _STRICT_TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING ({_BYPASS} OR {_TENANT_MATCH})
            WITH CHECK ({_BYPASS} OR {_TENANT_MATCH})
            """
        )

    # llm_config: tenant_id is nullable by design (scope='global'/'product' rows
    # have no owning tenant and must stay visible to every tenant session, or
    # the tenant->product->global resolution hierarchy in Section B.13 breaks
    # under RLS) -- unlike the strict tables above, a NULL tenant_id here means
    # "shared config", not "nobody's data".
    op.execute("ALTER TABLE llm_config ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE llm_config FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON llm_config
        USING ({_BYPASS} OR tenant_id IS NULL OR {_TENANT_MATCH})
        WITH CHECK ({_BYPASS} OR tenant_id IS NULL OR {_TENANT_MATCH})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY tenant_isolation ON llm_config")
    op.execute("ALTER TABLE llm_config NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE llm_config DISABLE ROW LEVEL SECURITY")

    for table in reversed(_STRICT_TENANT_TABLES):
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
