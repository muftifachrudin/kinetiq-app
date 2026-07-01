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
- Never pip-install a sibling monorepo package (e.g. `-e ../../../packages/db`)
  from a service's `requirements.txt` -- Railpack's native install step copies
  only `requirements.txt` into an isolated layer before the rest of the repo
  exists, so it fails with "not a valid editable requirement". Instead point
  `PYTHONPATH` at the sibling's source dir in `startCommand` (see
  `railway.toml`) so it's imported at runtime, once the full repo is present.

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
