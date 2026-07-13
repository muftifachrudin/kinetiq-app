# Kinetiq

Single-operator agentic trading system (BTC perp first) -- deterministic
signal modules -> arbiter -> risk hard gate -> shadow trading -> live canary,
with strict OOS walk-forward validation gates. No multi-tenant SaaS layer:
`apps/platform-core/*` (billing, agent-registry, api-gateway, etc.) and the
DB's tenant/RLS layer were dropped 13 July 2026 (migration
`0009_drop_platform_core_and_tenancy.py`) when scope narrowed from a
multi-vertical SaaS to this single focus. Full PRD, architecture, data
model, and roadmap: **`docs/prd.md`** (living doc -- keep it in sync
whenever a real architecture/infra decision changes, don't let it drift into
a stale snapshot). Deployment/infra gotchas: **`docs/deployment-runbook.md`**.
Project convention for how AI-assisted coding sessions on this repo should
flow (alignment -> planning -> execution -> review): **`docs/ai-coding-workflow.md`**
-- read it before starting a new feature.

## Language

Respond to the user in **Bahasa Indonesia** by default -- the founder's working
language across this whole project (chat, PRD, design briefs). This does NOT
apply to anything checked into the repo as code or engineering artifact: code,
comments, docstrings, commit messages, PR titles/descriptions, and CLAUDE.md
itself stay in **English**, matching the existing codebase convention (every
`.py`/`.ts`/`.yml` file and every commit so far).

**Everything under `docs/*.md` is Indonesian** (decision, 7 July 2026 --
previously only `docs/prd.md` and `docs/fib-gann-validation-brief.md` were
the exception, now extended to every doc in that folder including
`docs/deployment-runbook.md`), mixed with English technical terms where
that's how the founder actually writes/thinks (variable/function/table
names, jargon like "walk-forward"/"bootstrap CI", numbers/stats stay
as-is -- only the narrative/explanation is translated). Write new docs in
Indonesian directly; don't draft in English and translate after.

## Before touching Coolify, Neon, or CI config

**Compute runs on self-hosted Coolify** on a Vultr VM (migrated off Railway
13 July 2026 -- `docs/vultr-vm-migration-brief.md` has the history, superseded
by the Coolify decision; Railway is gone, not a fallback). Neon stays as the
DB, unchanged by this move. The same VM also runs Markoviz
(`ai-perp-bot-core`) live, **unmanaged by Coolify** (its own docker-compose,
internal-only ports) -- never assume a Coolify-side change is isolated from
it without checking `docker ps` on the host first; don't restart/stop
anything on that VM without the founder's explicit sign-off.

Read `docs/deployment-runbook.md` first. The short version of what's in there:

- Coolify deploys are **Docker-build based, not Railpack/buildpack** -- every
  deployable service needs its own `Dockerfile` (none existed under Railway;
  Railpack's zero-config Python detection has no Coolify equivalent worth
  relying on). A service that needs the sibling `packages/db` package must
  `COPY` it into its own image explicitly -- there is no repo-root
  Root-Directory workaround like Railway's.
- Neon's default/primary branch is named **`production`**, not `main` --
  don't assume git and Neon branch names match (`schema-diff-action`'s
  `base_branch` needs the Neon name).
- `DATABASE_URL` from Neon is a bare `postgresql://` URL; SQLAlchemy will
  default that to `psycopg2` unless forced to `psycopg` (v3). Every service
  must call `kinetiq_db.engine.normalize_db_url()` rather than
  `create_engine(os.environ["DATABASE_URL"])` directly.
- This session's sandbox may not be able to reach `console.neon.tech`
  directly, but GitHub Actions runners always can -- a PR is the real
  integration test for DB/migration changes, not "can I curl it from here."
- **CI passing does NOT mean the real `production` Neon branch is
  migrated.** `neon-preview-branch` only ever runs against a fresh,
  ephemeral, per-PR branch that gets deleted when the PR closes -- it says
  nothing about whether `alembic upgrade head` has ever run against
  whatever branch the live service's `DATABASE_URL` actually points to.
  Run migrations as an explicit deploy step (entrypoint/startCommand),
  never assume a prior manual run covers the next deploy.
- Kinetiq is single-operator: there is no tenant/RLS layer anymore (dropped
  in migration `0009`). `order_audit_log` is still append-only, but via a
  `BEFORE UPDATE OR DELETE` trigger (migration 0003) that enforces even
  against the table owner -- `REVOKE UPDATE, DELETE` alone would be a no-op
  for an owning role, which is why the trigger exists instead.

## Before pushing any infra/config change

Simulate the actual deploy platform locally, don't just run the app the easy
way: for a Coolify-deployed service, build the exact `Dockerfile` locally
(`docker build` from repo root, matching Coolify's build context) and run the
resulting image with the same env vars/command, then hit the healthcheck
path -- not just a bare `python main.py` in a dev venv. Validate TOML/YAML
syntax locally (`python3 -c "import tomllib; ..."`) before pushing. This is
what catches "works locally, fails on the real platform" bugs before a
deploy cycle burns time on it.

## Repo conventions

- `packages/db` is schema source of truth (SQLAlchemy + Alembic) --
  `docs/prd.md` describes the model, but the code is authoritative for
  actual column names/types.
- Path-sensitive files (`execution/risk_gate.py`, `execution/custody/*`,
  `packages/db/migrations/`) require manual review -- enforced by
  `.github/CODEOWNERS`, don't rely on CI auto-merge for these.
- **Commits on `origin/main` that were not authored in your sandbox are
  EXPECTED and normal** -- merges to main happen as GitHub squash merges
  via the API/UI, executed by the founder or by a different Claude session
  (multiple sessions work on this repo in parallel). This is the intended
  workflow, not an anomaly: do not flag it, do not warn about it each
  turn, and never rewrite or revert published main history over it. On
  seeing new commits on main, just `git fetch origin main && git checkout
  -B <your-branch> origin/main` (when your branch's PR was already merged)
  or rebase unmerged work onto `origin/main`, then continue.

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
- RESOLVED (2026-07-03, Fase 0d): `neondb_owner` has `rolbypassrls=true`,
  which made FORCE RLS a no-op for production traffic. Fixed by creating a
  non-owner `kinetiq_app` role (`rolbypassrls=false`, `rolsuper=false`, no
  `neon_superuser` membership, created via raw SQL as `neondb_owner` --
  Neon Console/API provisioning auto-enrolls new roles into
  `neon_superuser`, which carries BYPASSRLS) and switching both production
  services (`api-gateway`, `ingestion` worker) to connect as it, verified
  via real Railway Deploy Logs with zero permission errors. `api-gateway`
  keeps a separate `DATABASE_URL_MIGRATIONS` env var (still `neondb_owner`)
  for the `alembic upgrade head` startCommand step only, since `kinetiq_app`
  deliberately has no DDL rights (see `packages/db/migrations/env.py` and
  `railway.toml`). RLS-based tenant isolation claims are now valid in
  production. Full record: `docs/sonnet5-implementation-roadmap.md` Fase 0d.
- CoinGlass Hobbyist is confirmed daily-only (interval=1h returns 403);
  per-pair endpoints require `exchange=`; keep ~2.5s between calls.
- RESOLVED (2026-07-03): production `trade_annotation` is now populated
  (276 rows, `instrument` 55) -- the original `--emit-sql` file failed
  repeatedly via manual paste into Neon SQL Editor (large multi-statement
  pastes silently truncated on mobile well under the file's actual size,
  at ~140-150 lines regardless of byte count). Root cause turned out to be
  paste reliability, not the data/transaction itself. Fix: the Neon
  HTTP-SQL endpoint's `{"queries": [...]}` array form (see above) DOES
  correctly execute a large multi-statement transaction (BEGIN/set_config/
  156+ INSERTs/COMMIT in one request, confirmed at 159 queries / ~90KB
  payload) -- the earlier assumption in the deep-dive brief that this form
  was "fine for small reads but not bulk INSERT" was never actually tested
  and was wrong. Don't reach for manual Neon SQL Editor paste for bulk
  writes again; use the `queries` array from the sandbox/CI directly.
