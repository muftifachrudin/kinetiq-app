"""Grant least-privilege access to the kinetiq_app role (Fase 0d, docs/sonnet5-implementation-roadmap.md)

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-03

Root cause this exists to fix: `neondb_owner` (the role every service's
DATABASE_URL currently connects as) has `rolbypassrls=true` in production --
FORCE ROW LEVEL SECURITY (migration 0002) is completely ineffective for that
role's own connection, so tenant isolation today depends entirely on
`set_config` + application-level WHERE clauses, not RLS at all (see
CLAUDE.md's corresponding memory entry).

This migration does NOT create a login role. `CREATE ROLE ... LOGIN`
requires a password, which must never be committed to git, and a Postgres
role is a CLUSTER-level object anyway (not scoped to one database/
migration) -- so a login role is deliberately kept out of Alembic's hands
entirely. The founder creates `kinetiq_app` by hand, connected AS
`neondb_owner`, via the Neon SQL Editor -- NOT via the Neon Console/API,
which auto-enrolls console-created roles into `neon_superuser` membership
(which itself carries BYPASSRLS) -- reproducing the exact problem this
migration exists to fix. After creating the role, verify BOTH of:
    SELECT rolbypassrls FROM pg_roles WHERE rolname = 'kinetiq_app';
        -- must be false
    SELECT pg_roles.rolname FROM pg_auth_members
      JOIN pg_roles ON pg_roles.oid = pg_auth_members.roleid
      WHERE member = 'kinetiq_app'::regrole;
        -- must NOT include neon_superuser

The guarded CREATE ROLE below ONLY ever fires on a fresh local/CI Postgres
that has never seen `kinetiq_app` before -- it creates a NOLOGIN
placeholder (no password, safe to commit/run anywhere) purely so the GRANT
statements that follow have a role to target. In production, `kinetiq_app`
already exists (founder-created, LOGIN, real password) by the time this
migration runs there, so the guard's CREATE ROLE branch never executes
against production -- only the GRANTs do. This makes the migration itself
"inert": merging it changes nothing about which role production's
DATABASE_URL actually uses (that's a separate, manual, later step -- see
the roadmap doc's Fase 0d execution order, which requires explicit founder
confirmation before each step).

Grants cover the whole public schema (current tables via GRANT, future
tables via ALTER DEFAULT PRIVILEGES) rather than an enumerated table list:
kinetiq_app is meant to be THE application role for every service --
api-gateway AND the ingestion worker, which INSERTs/UPDATEs
ohlcv/funding_rate/open_interest directly (apps/products/trading/
ingestion/ingest.py) -- and RLS (already FORCE-enabled on the tenant-owned
tables, migration 0002) is what's meant to restrict row-level access, not
a hand-maintained per-table grant list that silently drifts out of sync as
new tables/services are added. SELECT/INSERT/UPDATE/DELETE is granted (not
just SELECT/INSERT): order_audit_log's real protection against UPDATE/
DELETE is its BEFORE trigger (migration 0003), which fires regardless of
the connecting role's raw SQL privileges, so restricting the GRANT itself
here would be redundant defense, not additional safety.

ALTER DEFAULT PRIVILEGES only affects objects created afterward BY THE
ROLE RUNNING THIS MIGRATION (always the owner role, since every migration
runs via DATABASE_URL_MIGRATIONS -- see railway.toml/env.py) -- so future
migrations' new tables automatically grant kinetiq_app access without
needing a follow-up grant migration each time.

Downgrade is REVOKE, deliberately NEVER DROP ROLE: dropping a role that
production might still be actively connected as (mid-rollback) would be
far more disruptive than revoking its privileges, and the role's own
existence isn't this migration's concern in the first place (see above --
it's created out-of-band by the founder, not by Alembic).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE = "kinetiq_app"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{_ROLE}') THEN
                CREATE ROLE {_ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {_ROLE}")


def downgrade() -> None:
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM {_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {_ROLE}")
    op.execute(f"REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM {_ROLE}")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM {_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_ROLE}")
