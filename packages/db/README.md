# Packages: DB

SQLAlchemy models (`src/kinetiq_db/models.py`) + Alembic migrations (`migrations/`) -- source of truth
schema (tenant/RLS, time-series derivatif, trading domain). See `docs/prd.md` Section B.3/B.6b/B.13.

Verified end-to-end (upgrade -> downgrade -> upgrade) against local PostgreSQL 16 on 2026-07-01:
30 objects created (23 regular tables + 7 range-partitioned tables, each with a `_default` catch-all
partition so the parent is usable before `infra/neon/partitioning/` rolls forward proper time-range
partitions).

Not yet done (needs a DB connection to Neon, which this session's network policy currently blocks
— see chat history): Postgres Row-Level Security policies (Section B.4), the append-only grant on
`order_audit_log` (revoke UPDATE/DELETE from the app role), and pgvector setup (Section C.1).

## Local dev

```bash
cd packages/db
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
export DATABASE_URL="postgresql+psycopg://<user>:<pass>@<host>/<db>"
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
