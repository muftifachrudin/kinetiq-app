"""Drop platform-core multi-tenant layer — Kinetiq is now single-operator

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-13

Kinetiq's scope narrowed from a multi-tenant trading SaaS to a
single-operator agentic trading system (docs/prd.md rewrite, same date).
`apps/platform-core/*` (billing, agent-registry, notification,
dashboard-shell, mcp-server, guardrails, agent-sdk, api-gateway) was
deleted in the same change — api-gateway was the only piece with real
code, and it was also the only code that ever set the `app.tenant_id`/
`app.is_superadmin` session vars migration 0002's RLS policies depend on.
With that code gone, RLS on the trading tables would silently stop doing
anything (or block everything, if `FORCE ROW LEVEL SECURITY` holds with
no session var ever set) — so it comes out explicitly here rather than
being left as dead, misleading policy.

Order matters: RLS/policies are dropped first (cheap, no dependency on
column state), then `tenant_id` columns are dropped from every remaining
trading table (this implicitly drops the FK constraint into `tenant`),
then the platform-core tables themselves are dropped with CASCADE — they
have a circular reference (tenant -> token_package -> platform_user ->
tenant) that isn't worth untangling by hand.

`risk_mandate`'s primary key was `(tenant_id, account_id)`; dropping
`tenant_id` needs an explicit PK swap to `account_id` alone, done via a
separate op.execute() sequence rather than SQLAlchemy's drop_column (which
doesn't understand PK membership).

`tenant_credential` is renamed to `credential` in the same migration:
keeping "tenant" in the name once there's no tenant column left would be
actively misleading to the next reader, and nothing outside
models.py/migrations/docs referenced the old name (checked via grep before
writing this).

DATA LOSS CAVEAT for downgrade(): this migration's upgrade() permanently
discards the `tenant_id` value on every existing row (there is no
"restore" for that — a real multi-tenant deployment rolling this back
would need to have kept an external copy of the tenant_id column before
upgrading). downgrade() recreates the schema shape (nullable tenant_id,
tenant/platform_user/etc. tables, RLS) but every re-added tenant_id is
NULL, and RLS's default-deny WITH CHECK means no session can write to
these tables again until either a superadmin session var is set or every
row is manually re-tagged with a real tenant_id. This is intentional: the
downgrade exists for schema-shape symmetry / CI round-trip testing, not
as a real production rollback plan for a decision that was made
deliberately, not accidentally.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same list as migration 0002's _STRICT_TENANT_TABLES, minus
# tenant_token_ledger (dropped wholesale below, not column-stripped).
_TENANT_SCOPED_TABLES = (
    "strategy",
    "portfolio_target",
    "position",
    "order_audit_log",
    "risk_mandate",
    "tenant_credential",
    "dlmm_position",
    "trade_annotation",
)

_PLATFORM_CORE_TABLES = (
    "tenant_token_ledger",
    "llm_config",
    "token_package",
    "platform_user",
    "tenant",
)


def upgrade() -> None:
    # 1. Drop RLS + policy on every still-existing tenant-scoped table.
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON llm_config")

    # 2. risk_mandate: swap composite PK (tenant_id, account_id) -> account_id
    #    before dropping the column (SQLAlchemy's drop_column doesn't know
    #    how to shrink a composite PK).
    op.execute("ALTER TABLE risk_mandate DROP CONSTRAINT risk_mandate_pkey")
    op.execute("ALTER TABLE risk_mandate DROP COLUMN tenant_id")
    op.execute("ALTER TABLE risk_mandate ADD PRIMARY KEY (account_id)")

    # 3. Every other tenant-scoped table: tenant_id was never part of the PK.
    for table in (
        "strategy",
        "portfolio_target",
        "position",
        "order_audit_log",
        "tenant_credential",
        "dlmm_position",
        "trade_annotation",
    ):
        op.execute(f"ALTER TABLE {table} DROP COLUMN tenant_id")

    # 4. Rename tenant_credential -> credential now that "tenant" no longer
    #    describes anything about this table. Renaming a table does NOT
    #    rename its constraints/sequence/indexes in Postgres — every one of
    #    those still carries the old `tenant_credential_*` prefix until
    #    renamed explicitly, which would otherwise leave exactly the kind
    #    of stale "tenant" naming this migration exists to clean up.
    op.execute("ALTER TABLE tenant_credential RENAME TO credential")
    op.execute(
        "ALTER TABLE credential RENAME CONSTRAINT "
        "tenant_credential_credential_type_check TO ck_credential_type"
    )
    op.execute("ALTER TABLE credential RENAME CONSTRAINT tenant_credential_pkey TO credential_pkey")
    op.execute("ALTER TABLE credential RENAME CONSTRAINT tenant_credential_venue_id_fkey TO credential_venue_id_fkey")
    op.execute("ALTER SEQUENCE tenant_credential_id_seq RENAME TO credential_id_seq")

    # 5. Drop the platform-core tables. CASCADE handles the circular FK
    #    (tenant -> token_package -> platform_user -> tenant) in one pass.
    op.execute("DROP TABLE IF EXISTS " + ", ".join(_PLATFORM_CORE_TABLES) + " CASCADE")


def downgrade() -> None:
    # 1. Recreate platform-core tables (mirrors 0001_initial_schema.py).
    op.execute(
        """
        CREATE TABLE tenant (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            plan_tier TEXT NOT NULL DEFAULT 'signal_only'
                CHECK (plan_tier IN ('signal_only','auto_execute','meme_addon','dlmm_addon')),
            payment_provider TEXT,
            payment_customer_id TEXT,
            payment_subscription_status TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE platform_user (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID REFERENCES tenant(id),
            clerk_user_id TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL DEFAULT 'tenant' CHECK (role IN ('superadmin','admin','tenant')),
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE llm_config (
            id SERIAL PRIMARY KEY,
            scope TEXT NOT NULL CHECK (scope IN ('global','product','tenant')),
            tenant_id UUID REFERENCES tenant(id),
            product_key TEXT,
            agent_skill_key TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'openrouter',
            model TEXT NOT NULL,
            params JSONB,
            updated_by UUID REFERENCES platform_user(id),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE token_package (
            id SERIAL PRIMARY KEY,
            package_key TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            monthly_token_allowance BIGINT NOT NULL,
            price_usd NUMERIC(10,2) NOT NULL,
            discount_pct NUMERIC(5,2) DEFAULT 0,
            is_addon_topup BOOLEAN DEFAULT FALSE,
            is_active BOOLEAN DEFAULT TRUE,
            updated_by UUID REFERENCES platform_user(id),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE tenant ADD COLUMN token_package_id INT REFERENCES token_package(id)")
    op.execute(
        """
        CREATE TABLE tenant_token_ledger (
            id BIGSERIAL PRIMARY KEY,
            tenant_id UUID REFERENCES tenant(id) NOT NULL,
            ts TIMESTAMPTZ DEFAULT now(),
            delta_tokens BIGINT NOT NULL,
            reason TEXT NOT NULL CHECK (reason IN ('monthly_reset','consumption','topup_purchase','admin_adjustment')),
            agent_skill_key TEXT,
            balance_after BIGINT NOT NULL
        )
        """
    )

    # 2. Rename credential back to tenant_credential and add tenant_id back
    #    (nullable — see module docstring's data-loss caveat). The CHECK
    #    constraint MUST be restored to its exact original auto-generated
    #    name (`tenant_credential_credential_type_check`, what 0001's
    #    unnamed inline CHECK produces) rather than a "cleaner" name —
    #    upgrade() unconditionally renames FROM that exact string, so a
    #    second upgrade() after this downgrade() would fail to find it
    #    otherwise. Caught by an actual upgrade->downgrade->upgrade round
    #    trip run locally; PK/FK/sequence renames below don't have this
    #    problem since their up/down names already match symmetrically.
    op.execute("ALTER TABLE credential RENAME TO tenant_credential")
    op.execute(
        "ALTER TABLE tenant_credential RENAME CONSTRAINT "
        "ck_credential_type TO tenant_credential_credential_type_check"
    )
    op.execute("ALTER TABLE tenant_credential RENAME CONSTRAINT credential_pkey TO tenant_credential_pkey")
    op.execute("ALTER TABLE tenant_credential RENAME CONSTRAINT credential_venue_id_fkey TO tenant_credential_venue_id_fkey")
    op.execute("ALTER SEQUENCE credential_id_seq RENAME TO tenant_credential_id_seq")
    op.execute("ALTER TABLE tenant_credential ADD COLUMN tenant_id UUID REFERENCES tenant(id)")

    # 3. Add tenant_id back (nullable) to every other tenant-scoped table.
    for table in (
        "strategy",
        "portfolio_target",
        "position",
        "order_audit_log",
        "dlmm_position",
        "trade_annotation",
    ):
        op.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id UUID REFERENCES tenant(id)")

    # 4. risk_mandate: swap PK back to (tenant_id, account_id).
    op.execute("ALTER TABLE risk_mandate ADD COLUMN tenant_id UUID REFERENCES tenant(id)")
    op.execute("ALTER TABLE risk_mandate DROP CONSTRAINT risk_mandate_pkey")
    op.execute("ALTER TABLE risk_mandate ADD PRIMARY KEY (tenant_id, account_id)")

    # 5. Re-enable RLS + recreate policies (mirrors 0002_add_rls_policies.py).
    _bypass = "current_setting('app.is_superadmin', true) = 'true'"
    _tenant_match = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    for table in (
        "tenant_token_ledger",
        "strategy",
        "portfolio_target",
        "position",
        "order_audit_log",
        "risk_mandate",
        "tenant_credential",
        "dlmm_position",
        "trade_annotation",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING ({_bypass} OR {_tenant_match})
            WITH CHECK ({_bypass} OR {_tenant_match})
            """
        )
    op.execute("ALTER TABLE llm_config ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE llm_config FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON llm_config
        USING ({_bypass} OR tenant_id IS NULL OR {_tenant_match})
        WITH CHECK ({_bypass} OR tenant_id IS NULL OR {_tenant_match})
        """
    )
