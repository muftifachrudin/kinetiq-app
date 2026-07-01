# Packages: DB

SQLAlchemy models (`src/kinetiq_db/models.py`) + Alembic migrations (`migrations/`) -- source of truth
schema (tenant/RLS, time-series derivatif, trading domain). See `docs/prd.md` Section B.3/B.6b/B.13.

Verified end-to-end (upgrade -> downgrade -> upgrade) against local PostgreSQL 16 on 2026-07-01:
32 objects created (25 regular tables + 7 range-partitioned tables, each with a `_default` catch-all
partition so the parent is usable before `infra/neon/partitioning/` rolls forward proper time-range
partitions). Includes `token_package`/`tenant_token_ledger` (Section B.15, token-based usage billing)
and the generalized `tenant.payment_provider`/`payment_customer_id`/`payment_subscription_status`
columns (Section B.16 — provider-agnostic, not locked to any single payment gateway).

CI's `neon-preview-branch` job (real Neon, not local Postgres) has actually created Neon branches
successfully against the project's real `NEON_API_KEY`/`NEON_PROJECT_ID` — connectivity is proven.
The migration step itself failed there with `ModuleNotFoundError: No module named 'psycopg2'`
because `create-branch-action`'s output is a bare `postgresql://` URL, which makes SQLAlchemy default
to the psycopg2 dialect instead of the `psycopg` (v3) driver this project actually depends on. Fixed
in `migrations/env.py` by forcing the `+psycopg` drivername on whatever `DATABASE_URL` is passed in
(verified locally against a bare `postgresql://` DSN, not just the `+psycopg` form).

**Row-Level Security (Section B.4) is now live** as of `0002_add_rls_policies.py`: `tenant_isolation`
policies on the 9 tenant-owned domain tables (`tenant_token_ledger`, `strategy`, `portfolio_target`,
`position`, `order_audit_log`, `risk_mandate`, `tenant_credential`, `dlmm_position`, `trade_annotation`)
plus `llm_config` (with a NULL-tenant_id exception so global/product-scope rows stay visible to every
tenant, per the resolution hierarchy in Section B.13). `platform_user` deliberately has no RLS policy
-- `api-gateway/deps.py` looks a caller up by `clerk_user_id` *before* any tenant_id is known, and
scoping that lookup would break login entirely. Uses `FORCE ROW LEVEL SECURITY` because the app's
`DATABASE_URL` role is currently the same role that owns these tables (no separate least-privilege
app role provisioned yet) -- without FORCE, Postgres exempts the owner from RLS and the policies
would be silent no-ops against the app's own queries. A dedicated non-owner app role (a stronger
defense-in-depth layer than FORCE + session variables alone) remains a good future hardening step,
not done here. Verified locally end-to-end against a non-superuser owner role (mirroring the
production connection): cross-tenant reads return zero rows, cross-tenant writes are rejected by
`WITH CHECK`, and a session with no tenant context set at all sees nothing (fails closed) -- see
`docs/deployment-runbook.md` for the full verification method and a real gotcha this surfaced
(`SET x = :param` doesn't accept bind parameters in Postgres; use `set_config()` instead).

**`order_audit_log` is now genuinely append-only** as of `0003_order_audit_log_append_only.py`: not
via `REVOKE` (a no-op against the table's owner, same reasoning as why RLS needed `FORCE` above), but
a `BEFORE UPDATE OR DELETE` trigger that unconditionally raises -- verified locally to reject both
operations even when connected as the `postgres` superuser/owner, with no bypass for any role.

Still not done: pgvector setup (Section C.1).

## Local dev

```bash
cd packages/db
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
export DATABASE_URL="postgresql://<user>:<pass>@<host>/<db>"   # +psycopg is forced automatically, see migrations/env.py
alembic upgrade head      # apply
alembic downgrade base    # roll back everything
alembic current           # check applied revision
```

## Against Neon

```bash
export DATABASE_URL="<connection string from Neon Console -> Connection Details>"
alembic upgrade head
```

Use a Neon branch (not the primary `main` branch) for anything experimental — Neon's
copy-on-write branching makes this cheap, and CI is designed to do this automatically per-PR
(see `docs/prd.md` Section C.3).
