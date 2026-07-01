# Kinetiq

Multi-agent AI trading SaaS (perp/spot MVP, meme-sniper & DLMM as later
modules), built on an agent-agnostic Platform Core. Full PRD, architecture,
data model, and roadmap: **`docs/prd.md`** (living doc -- keep it in sync
whenever a real architecture/infra decision changes, don't let it drift into
a stale snapshot). Deployment/infra gotchas: **`docs/deployment-runbook.md`**.

## Before touching Railway, Neon, or CI config

Read `docs/deployment-runbook.md` first. The short version of what's in there:

- `railway.toml` must live at **repo root**, never inside a service's Root
  Directory -- Railway's config-as-code resolution ignores Root Directory,
  though commands inside the file still execute relative to it.
- Don't override `[build] buildCommand` for a Python service on Railway.
  Railpack has solid native install-step support for plain `requirements.txt`
  projects, not for bare `pyproject.toml`/setuptools ones (no Poetry/uv) --
  use a flat `main.py` + `requirements.txt`, not a `src/`-layout package.
- Use `python -m uvicorn ...` (or `python -m <tool>` generally) in
  `startCommand`, never a bare console-script binary -- Railpack's
  mise-managed Python doesn't reliably put shims on the deploy stage's PATH.
- Neon's default/primary branch is named **`production`**, not `main` --
  don't assume git and Neon branch names match (`schema-diff-action`'s
  `base_branch` needs the Neon name).
- `DATABASE_URL` from Neon/Railway is a bare `postgresql://` URL; SQLAlchemy
  will default that to `psycopg2` unless forced to `psycopg` (v3). Every
  service must call `kinetiq_db.engine.normalize_db_url()` rather than
  `create_engine(os.environ["DATABASE_URL"])` directly -- this bit two
  separate services (`packages/db/migrations/env.py` and
  `apps/platform-core/api-gateway/deps.py`) before it was made shared.
- This session's sandbox may not be able to reach `console.neon.tech`
  directly, but GitHub Actions runners always can -- a PR is the real
  integration test for DB/migration changes, not "can I curl it from here."
- When a Railway deploy fails, get **both** Build Logs (dependency install
  success/failure) and Deploy Logs (actual container stdout, crash traces,
  healthcheck attempts) -- they show different failure classes and a
  healthcheck failure looks identical whether the app crashed instantly or
  it's a real networking issue.
- A service whose Railway Root Directory is a subfolder (e.g.
  `apps/platform-core/api-gateway`) can **never** reach a sibling directory
  like `packages/db` -- not via `-e ../../../packages/db` in
  `requirements.txt`, not via a subfolder-relative `PYTHONPATH` either.
  Root Directory scopes the entire build+runtime context to that one
  subfolder; siblings are never copied in, period. Fix: set Root Directory
  to the **repo root**, move `requirements.txt` to repo root too (so
  Railpack's zero-config Python detection still fires), and set
  `PYTHONPATH` in `startCommand` to include both the sibling package's
  source dir and the service's own folder (see `railway.toml`).
- Never `SET x = :param` with a bind parameter -- Postgres rejects it as a
  syntax error (`SET` isn't DML, no extended-protocol parameter support).
  Use `SELECT set_config('x', :param, false)` instead. Also: an `app.*`
  custom GUC that's never been set *in the current session* can read back
  as `''` rather than `NULL` via `current_setting(name, true)` once any
  session anywhere has used that GUC name -- wrap with
  `NULLIF(current_setting(...), '')` before casting. Full RLS gotchas
  (including why `FORCE ROW LEVEL SECURITY` is required and why
  `platform_user` has no RLS policy) are in `docs/deployment-runbook.md`.
- Don't use `REVOKE UPDATE, DELETE ...` to make a table append-only if the
  app's role owns that table -- object owners always retain full privileges
  regardless of GRANT/REVOKE (no `FORCE`-like override exists for this,
  unlike RLS). Use a `BEFORE UPDATE OR DELETE` trigger that raises instead --
  it enforces even against the owner. See `order_audit_log`'s trigger in
  migration 0003 and `docs/deployment-runbook.md`.

## Before pushing any infra/config change

Simulate the actual deploy platform locally, don't just run the app the easy
way: for a Railway/Railpack Python service, use a **fresh venv** +
`pip install -r requirements.txt` (not an existing dev venv, not an editable
install) + the exact declared `startCommand`, then hit the healthcheck path.
Validate TOML/YAML syntax locally (`python3 -c "import tomllib; ..."`) before
pushing. This is what catches "works locally, fails on the real platform"
bugs before a deploy cycle burns time on it.

## Repo conventions

- `packages/db` is schema source of truth (SQLAlchemy + Alembic) --
  `docs/prd.md` Section B.3/B.6b/B.13 describes the model, but the code is
  authoritative for actual column names/types.
- Path-sensitive files (`execution/risk_gate.py`, `execution/custody/*`,
  `packages/db/migrations/`) require manual review -- enforced by
  `.github/CODEOWNERS`, don't rely on CI auto-merge for these.
