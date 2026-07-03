# Kinetiq

Multi-agent AI trading SaaS (perp/spot MVP, meme-sniper & DLMM as later
modules), built on an agent-agnostic Platform Core. Full PRD, architecture,
data model, and roadmap: **`docs/prd.md`** (living doc -- keep it in sync
whenever a real architecture/infra decision changes, don't let it drift into
a stale snapshot). Deployment/infra gotchas: **`docs/deployment-runbook.md`**.

## Language

Respond to the user in **Bahasa Indonesia** by default -- the founder's working
language across this whole project (chat, PRD, design briefs). This does NOT
apply to anything checked into the repo as code or engineering artifact: code,
comments, docstrings, commit messages, PR titles/descriptions, and CLAUDE.md/
`docs/deployment-runbook.md` itself stay in **English**, matching the existing
codebase convention (every `.py`/`.ts`/`.yml` file and every commit so far).
`docs/prd.md` and `docs/fib-gann-validation-brief.md` are the exception --
those are already written in Indonesian (mixed with English technical terms
where that's how the founder actually writes/thinks), keep new edits to them
in that same style rather than switching to English.

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
- **CI passing does NOT mean the real `production` Neon branch is
  migrated.** `neon-preview-branch` only ever runs against a fresh,
  ephemeral, per-PR branch that gets deleted when the PR closes -- it says
  nothing about whether `alembic upgrade head` has ever run against
  whatever branch Railway's `DATABASE_URL` actually points to. This bit
  production for real: `platform_user` (and every other table) never
  existed there at all until `railway.toml`'s `startCommand` was changed
  to run `(cd packages/db && python -m alembic upgrade head)` before
  `uvicorn` starts, every deploy. Every prior deploy "worked" only because
  no request had yet reached a real DB query with a real auth token.
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

## Validation & strategy-research memory (July 2026 deep-dive)

Read BEFORE any work on `fib_gann_timing`, the validation harness, scoring
weights, or derivatives data. Full record: findings + theory v2 + score
rubric in `docs/validation-deep-dive-2026-07.md` (Indonesian); evidence
trail, reproduction steps, and claim-status table in
`docs/fable5-crypto-theory-investigation-2026-07.md`; the phased execution
plan for the next implementation sessions in
`docs/sonnet5-implementation-roadmap.md`. Non-negotiables distilled from
that work:

- The first real walk-forward run FAILED promotion (PF net > 1.3 in only
  2/10 windows, BTC 1h Binance). Replicated across 4 series: robust
  cross-venue (~73% signal overlap, near-identical PF Binance vs Bybit)
  but does NOT generalize to ETH. All tested on USDT-M **perp**, never spot.
- The hand-tuned `ConfluenceWeights` confidence is ANTI-predictive
  (pearson r = -0.05 over 2,679 labeled trades). Do not add new hand-tuned
  score constants; the 2,679 triple-barrier labels from the replication
  removed the old "no data to fit" blocker -- fit weights instead
  (roadmap Phase 3).
- Backtest PF is currently gross of trading fees, and fees are material
  (0.10% round-trip taker flips mean trade negative) while funding is
  negligible at ~11h holds. Any PF quoted without "net of fees" is
  incomplete.
- OI-fuel is a coincident/volatility-regime indicator, not a directional
  predictor (strong same-day replication 1.8-2.7x, weak H+1, zero effect
  on trade outcomes). Don't wire it as a direction weight.
- In-sample numbers are hypotheses. The PF 0.97 -> 1.30 lift from
  SMA200-alignment + RR in [2,5) was found on the same data that inspired
  it -- adoption only via out-of-sample walk-forward, net of fees.
- Neon HTTP-SQL endpoint: single statement via `{"query": ...}`;
  multi-statement with preserved session state via
  `{"queries": [{"query": ...}, ...]}` (array of OBJECTS; plain strings
  are rejected). Raw Postgres connections still hang from the sandbox.
- `neondb_owner` has `rolbypassrls=true` in production, so FORCE RLS does
  NOT protect anything for services connecting as that role. Don't claim
  RLS-based tenant isolation in production until services run as a
  non-owner, non-BYPASSRLS role (roadmap Phase 0d).
- CoinGlass Hobbyist is confirmed daily-only (interval=1h returns 403);
  per-pair endpoints require `exchange=`; keep ~2.5s between calls.
- OPEN data-integrity issue: production `trade_annotation` is EMPTY
  (0-byte heap, 4 instruments) despite the import recorded as verified in
  the brief section 21 -- founder must re-run the --emit-sql import and
  verify the count from a separate session before any agreement-rate/
  shadow-pair work.
