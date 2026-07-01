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

Not yet done (needs Postgres role/permission work best done directly against Neon): Row-Level
Security policies (Section B.4), the append-only grant on `order_audit_log` (revoke UPDATE/DELETE
from the app role), and pgvector setup (Section C.1).

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
