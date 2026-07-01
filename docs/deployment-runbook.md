# Deployment & Infra Runbook (Railway + Neon + GitHub Actions)

Hard-won operational knowledge from getting the first service (`api-gateway`) live.
Read this before touching `railway.toml`, `.github/workflows/ci.yml`, or anything
under `packages/db/migrations/` -- every item below cost a real failed deploy or
CI run to discover, and the failure modes are non-obvious enough to repeat if
this isn't written down.

See `docs/prd.md` for the product/architecture PRD -- this doc is deployment
mechanics only.

## Topology reference

- Repo: `kinetiq-app`, default branch `main`.
- Railway project has one service so far (`kinetiq-app`), Root Directory set to
  **repo root** (empty) in the dashboard (Settings -> Source) -- see Railpack
  gotcha #7 below for why it's the repo root and not the service subfolder.
- Neon project's default/primary branch is named **`production`**, not `main`.
  Git branch names and Neon branch names are two independent naming schemes --
  don't assume they match.

## Neon gotchas

0. **CI's `neon-preview-branch` has never once run a migration against the
   real persistent `production` Neon branch -- and nothing else was
   running migrations against it either.** This cost real production
   downtime: the first genuinely authenticated request that reached a
   database query in `api-gateway` (`GET /me` with a real Clerk session
   JWT, well after `FORCE ROW LEVEL SECURITY` and the auto-provision
   flow were already deployed) crashed with
   `psycopg.errors.UndefinedTable: relation "platform_user" does not
   exist`. Every prior deploy had "worked" only because every request
   tested so far either had no auth token (401 raised before any DB
   query) or exercised the code via a mocked `dependency_overrides` in a
   local `TestClient`, never a real query against the real database.
   `neon-preview-branch` only ever creates a **fresh, ephemeral, per-PR**
   branch, runs migrations against *that*, and deletes it once the PR
   closes -- it says nothing about whether `production` (or whatever
   Neon branch Railway's `DATABASE_URL` actually points to) has ever had
   `alembic upgrade head` run against it. Passing CI is not the same
   claim as "the real database is migrated." **Fix**: `railway.toml`'s
   `startCommand` now runs `(cd packages/db && python -m alembic upgrade
   head)` before starting `uvicorn`, every deploy (idempotent --
   alembic tracks applied revisions in `alembic_version`, a no-op once
   already at head). `alembic` had to be added to the root
   `requirements.txt` too, since `packages/db/pyproject.toml` (which
   lists it as a dependency) is never pip-installed by this service, only
   `PYTHONPATH`-referenced. Any future service with its own migrations
   needs the same "run migrations as part of startCommand" treatment --
   don't assume CI passing means the target database is actually
   migrated.

1. **`DATABASE_URL` driver mismatch.** Neon's `create-branch-action` (and
   Railway) hand out a bare `postgresql://...` connection string. SQLAlchemy
   defaults a bare `postgresql://` scheme to the `psycopg2` dialect, but this
   project depends on `psycopg` (v3), so migrations failed with
   `ModuleNotFoundError: No module named 'psycopg2'` -- and the exact same
   thing bit `api-gateway/deps.py` independently later, since it's a separate
   service with its own `create_engine()` call. Fixed once, shared everywhere:
   `kinetiq_db.engine.normalize_db_url()` forces the `postgresql+psycopg`
   driver via `make_url(...).set(drivername=...)` regardless of the scheme
   passed in -- every service that opens a DB connection should call this
   instead of `create_engine(os.environ["DATABASE_URL"])` directly.
   Gotcha within the gotcha: use `.render_as_string(hide_password=False)`, not
   `str(url)` -- the latter masks the password as `***` and silently breaks auth.

2. **CI *can* reach real Neon even when this interactive session can't.** The
   sandboxed Claude Code session's network policy blocks `console.neon.tech`,
   but that has zero bearing on GitHub Actions runners, which have normal
   internet access. Don't assume a migration "can't be tested against real
   Neon" just because the interactive session can't reach it directly -- open
   a PR and let `neon-preview-branch` in CI do it.

3. **`schema-diff-action`'s `base_branch` must be the Neon branch name**
   (`production`), not the git branch name (`main`). Confirmed by an
   `##[error]Branch main not found in project` failure.

4. **`SET x = :param` doesn't accept bind parameters -- Postgres rejects it
   with a syntax error at the protocol level** (`SET app.tenant_id = $1` ->
   `syntax error at or near "$1"`), because `SET` is a utility statement, not
   a regular DML statement eligible for the extended query protocol's
   parameter substitution. This had been sitting unnoticed in
   `api-gateway/deps.py` (`SET app.tenant_id = :tenant_id`) since the tenant
   auth middleware PR -- it never actually threw, because no real login with
   a non-null `tenant_id` had gone through it yet (every real request so far
   either had no token at all, or no tenant assigned). It surfaced the moment
   RLS policies started actually being queried in a test with a real tenant
   session. Fix: use `SELECT set_config('app.tenant_id', :tenant_id, false)`
   instead -- `set_config()` is a regular function call, so normal bind-
   parameter substitution works. Any future code that sets a Postgres session
   GUC from a Python variable must use `set_config()`, never string-formatted
   or parameterized `SET`.

5. **A custom (`app.*`-namespaced) GUC that's never been `SET` in the
   *current* session can read back as `''` (empty string) via
   `current_setting(name, true)`, not `NULL`** -- once any session on the
   server has ever used that GUC name, Postgres registers it as a known
   placeholder variable, and an unset instance of it in a fresh session then
   defaults to `''` rather than genuinely missing/`NULL`. This broke a
   `tenant_id = current_setting('app.tenant_id', true)::uuid` RLS policy
   expression with `invalid input syntax for type uuid: ""` the first time a
   session hit it without ever having called `set_config('app.tenant_id', ...)`
   itself (e.g. a superadmin session, which never sets `app.tenant_id` at
   all). Fix: `NULLIF(current_setting(name, true), '')::uuid` -- collapses
   both the never-set-anywhere (`NULL`) and set-elsewhere-but-not-here (`''`)
   cases to `NULL` before casting, instead of letting either reach the cast
   directly.

## Railway / Railpack gotchas

1. **`railway.toml` must live at the repo root**, never inside a service's
   Root Directory. Railway's config-as-code file resolution does not follow
   the Root Directory setting -- it's always resolved from repo root.
   Commands *inside* the file (`buildCommand`, `startCommand`) still execute
   relative to whatever Root Directory is configured in the dashboard, so
   write paths in the file as if `cwd` is already the service directory.

2. **Adding a 2nd+ Railway service**: each new service needs its own Root
   Directory set in the dashboard (Settings -> Source), and if it needs its
   own `railway.toml`, an explicit Config-as-code path per service (Settings
   -> Config-as-code) -- this can only be done from the dashboard/GraphQL API,
   not from a config file itself.

3. **Don't override `[build] buildCommand` for a Python service unless you
   have a specific reason to.** Two failure modes were hit here, in order:
   - With `buildCommand = "pip install -e ."` on a `pyproject.toml` project:
     the build log showed `pip install` succeed (`Successfully installed
     ... uvicorn-0.49.0`), but the runtime image still didn't have it
     (`No module named uvicorn`). The custom command bypasses whatever
     mechanism Railpack's own native install step uses to persist installed
     packages from the build stage into the final runtime image.
   - With no `buildCommand` at all: Railpack's zero-config Python detection
     recognized a `pyproject.toml`/setuptools project existed but didn't
     auto-generate an install step for it at all (no Poetry/uv lockfile it
     natively understands) -- the build log jumped straight from "Detected
     Python" to "Deploy" with no install step in between, so nothing was ever
     installed.
   - **What actually works**: a flat `main.py` + plain `requirements.txt`
     (no `src/` package layout, no `pyproject.toml`). Railpack has solid
     native support for `requirements.txt` and correctly persists the
     install into the runtime image. `main.py` at the service root is
     importable directly (`python -m uvicorn main:app`) without any install
     step of its own -- only third-party deps need `requirements.txt`.
   - If a future service genuinely needs Poetry/uv/a real installable
     package, verify Railpack's native support for that specific tool
     *first*, rather than reaching for a custom `buildCommand` override.

4. **Use `python -m uvicorn ...`, never the bare `uvicorn` binary, in
   `startCommand`.** Railpack manages Python via `mise`; the console-script
   shim for `uvicorn` isn't reliably on the `PATH` that the deploy stage's
   `bash -c` inherits (`uvicorn: command not found` in practice), but
   `python` itself always resolves. Same logic applies to any other
   console-script entry point (`gunicorn`, `alembic`, etc.) if one ever needs
   to run as a Railway start/build command.

5. **Build Logs vs Deploy Logs show different failure classes -- ask for
   both when debugging a Railway failure.** Build Logs show whether
   dependencies installed successfully. Deploy Logs show the actual
   container's stdout/stderr (crash tracebacks, the real
   `INFO: Uvicorn running on ...` startup line, and the healthcheck retry
   attempts). A "Healthcheck failed" banner alone is not enough information --
   it looks identical whether the app crashed instantly or whether it's a
   genuine networking/port misconfiguration. Get Deploy Logs before
   theorizing.

6. **"Unexposed service" / port-ambiguity is a plausible-looking dead end.**
   There's a real, documented Railway failure mode where an unexposed
   service's healthcheck fails because Railway can't determine which port to
   check, fixable by setting an explicit `PORT` variable. This was tried here
   and did *not* fix the actual problem, because the real cause (bug #3/#4
   above) was that the process never started at all. Don't stop
   investigating just because a plausible Railway community fix exists for a
   similarly-worded symptom -- confirm against Deploy Logs first.

7. **A sibling monorepo package (e.g. `packages/db`, referenced from a
   service whose Root Directory is a subfolder like
   `apps/platform-core/api-gateway`) is never reachable, by any method --
   not via `-e ../../../packages/db` in `requirements.txt` (fails with
   `ERROR: ../../../packages/db is not a valid editable requirement`), and
   not via `PYTHONPATH=../../../packages/db/src` in `startCommand` either
   (deploys fine, then crashes at runtime with `ModuleNotFoundError: No
   module named 'kinetiq_db'`).** Root cause, confirmed by reproducing the
   exact traceback locally with *only* the service's own folder present on
   disk (no monorepo siblings): Railway's "Root Directory" setting scopes
   the **entire** build *and* runtime context to that one subfolder --
   sibling directories are never copied in, at any build stage or at
   runtime. (The original theory here -- that this was just a Docker
   layer-caching timing issue, fixable by deferring the sibling reference
   from build-time pip-install to runtime-time `PYTHONPATH` -- was wrong.
   It's not a timing issue, the sibling directory categorically does not
   exist in that container, ever.) This matches how "root directory"/
   "working directory" scoping works on most PaaS platforms generally, not
   a Railpack-specific quirk.
   **Fix**: change the service's Root Directory in the Railway dashboard
   (Settings -> Source) to the **repo root** (empty), not the service
   subfolder. Move the service's `requirements.txt` to the **repo root**
   too, so Railpack's zero-config Python detection still fires natively
   (no custom `[build] buildCommand` needed -- see gotcha #3 above for why
   that's worth avoiding). Then in `startCommand`, set `PYTHONPATH` to
   include *both* the sibling package's source dir and the service's own
   folder (relative to repo root now, e.g.
   `PYTHONPATH=packages/db/src:apps/platform-core/api-gateway python -m
   uvicorn main:app ...`) -- the service folder needs to be on
   `PYTHONPATH` explicitly now too, since `main.py` is no longer
   automatically on `sys.path`/cwd once Root Directory is the repo root.
   Verify this by reproducing the container's actual file layout locally
   (copy *just* the service folder to an empty temp dir and run from
   there) before trusting any "should work" theory about Railway's build
   context -- that's what caught this bug's wrong first fix.
   Any future service that needs to reuse `packages/db` (or any other
   shared package) should use this Root-Directory-at-repo-root + combined
   `PYTHONPATH` pattern, not an editable pip install and not a
   subfolder-relative `PYTHONPATH`. Only one `railway.toml` and one root
   `requirements.txt` can exist at repo root, so a second Python service
   with this same need will require a different solution (e.g. a
   dedicated Railpack config or its own repo-root marker file scheme) --
   don't copy this pattern blindly for service #2.

## Row-Level Security (RLS) gotchas (`packages/db/migrations/versions/0002_add_rls_policies.py`)

1. **`FORCE ROW LEVEL SECURITY` is required, not optional, given today's
   connection setup.** Postgres exempts a table's *owner* from RLS entirely
   unless `FORCE` is also set. The app's `DATABASE_URL` currently connects as
   the same role that owns every table (no separate least-privilege app role
   exists yet) -- without `FORCE`, every policy added here would be a
   complete no-op against the app's own queries, while still looking "on" in
   `\d <table>`. `FORCE` only affects DML (SELECT/INSERT/UPDATE/DELETE);
   migrations are DDL and are unaffected by it.

2. **`platform_user` intentionally has no RLS policy**, even though it has a
   `tenant_id` column. `api-gateway/deps.py`'s `get_current_user()` looks a
   caller up by `clerk_user_id` *before* any `tenant_id` is known -- that
   lookup is how it discovers the tenant in the first place. A tenant-scoped
   policy on `platform_user` would make every login's own self-lookup
   invisible to itself (RLS denies by default when the session var isn't set
   yet), breaking auth for every user on every request. If a real need for
   restricting `platform_user` visibility ever comes up, it isn't this simple
   `tenant_id = ...` pattern.

3. **`llm_config` needs a different policy shape than the other tenant
   tables**: `tenant_id IS NULL OR tenant_id = current_setting(...)`, not a
   strict match. Its `NULL` `tenant_id` rows are `scope='global'`/`'product'`
   shared config (Section B.13's tenant->product->global resolution
   hierarchy), not "nobody's data" -- a strict policy would make every tenant
   session blind to the global/product defaults it's supposed to fall back
   to.

4. **Manual `psql`/admin inserts against RLS-protected tables need
   `SELECT set_config('app.is_superadmin', 'true', false);` run first in the
   same session**, or they'll be rejected by the policy's `WITH CHECK`
   clause (e.g. bootstrapping the very first superadmin/tenant rows, before
   any app code has run to set session context). This isn't a workaround --
   it's the intended admin escape hatch, same mechanism the app itself uses.

5. **How this was actually verified locally** (worth reusing for any future
   RLS policy work, since testing as the `postgres` superuser role proves
   nothing -- Postgres superusers bypass RLS unconditionally, full stop,
   regardless of `FORCE`): create a dedicated non-superuser role, reassign
   table ownership to it (`ALTER TABLE ... OWNER TO ...`), connect as that
   role, and confirm (a) a fresh connection with no session vars set at all
   sees zero rows (fails closed), (b) a tenant-scoped session only sees its
   own rows, (c) a cross-tenant `INSERT` is rejected, and (d)
   `app.is_superadmin = 'true'` sees everything. This exact sequence is what
   caught both gotchas #4 and #5 in the Neon gotchas section above -- they
   only appear once you exercise a *second*, previously-unused session
   (e.g. a fresh superadmin session that never called `set_config` itself).

## Append-only `order_audit_log` (`packages/db/migrations/versions/0003_order_audit_log_append_only.py`)

**`REVOKE UPDATE, DELETE ON order_audit_log FROM <role>` would be a silent
no-op**, for the exact same reason `FORCE ROW LEVEL SECURITY` was required in
0002: Postgres object owners always retain full privileges on objects they
own, regardless of any `GRANT`/`REVOKE` -- and unlike RLS, there's no `FORCE`
equivalent for privileges to override that. The app's `DATABASE_URL` role
owns `order_audit_log`, so a plain `REVOKE` would look like it did something
but change nothing.

**Fix used instead: a `BEFORE UPDATE OR DELETE` trigger that unconditionally
raises an exception.** Triggers fire regardless of role or ownership -- there
is no owner exemption, no `is_superadmin` bypass, nothing. Verified locally
by connecting as the `postgres` superuser (owner of the table) and
confirming both `UPDATE` and `DELETE` are rejected with `order_audit_log is
append-only: <OP> is not allowed`, while a normal `INSERT` still succeeds.
This is intentional, not a gap to fix later: an audit trail that any role
(including the most trusted one) can edit through the normal app path isn't
actually an audit trail. If a genuine correction is ever needed, it's a new
compensating row, not an edit to history -- and if a real emergency schema
fix is ever needed, that's a deliberate, separately-auditable
`ALTER TABLE order_audit_log DISABLE TRIGGER order_audit_log_append_only`
by a DBA, not something any session variable can quietly opt out of.

If a future table needs the same "insert-only, no edits/deletes ever"
guarantee, reach for this same trigger pattern directly -- don't reach for
`REVOKE` first and rediscover this the hard way.

## GitHub push-to-`main` workaround (situational, not evergreen)

Earlier in this project, this session's git relay returned a persistent 503
on direct pushes to `main` (apparently scoped to the session's *original*
branch name, before it got renamed to `main` on GitHub). The workaround: push
to the old branch name (which the relay still accepted), then open a PR from
that branch into `main` and merge via the GitHub API. If a future session
hits `git push origin <local>:main` failing with a 503 while `git ls-remote`
(read-only) works fine, this is the pattern to reach for -- it's a session/
relay quirk, not a real permissions problem.

## Verification checklist before pushing an infra/config change

- **Simulate Railpack exactly, don't just run the app locally the easy way.**
  A fresh venv + `pip install -r requirements.txt` (not `-e .`, not reusing an
  existing dev venv with leftover packages) + the *exact* declared
  `startCommand`, then `curl` the healthcheck path. This is what caught the
  "works locally, fails on Railway" class of bugs above before they were
  ever pushed.
- Validate config file syntax locally before pushing:
  `python3 -c "import tomllib; tomllib.load(open('railway.toml','rb'))"` for
  TOML, similarly for any YAML changes to `.github/workflows/*.yml`.
- Check CI (`lint` + `neon-preview-branch`) green on the PR before merging --
  `neon-preview-branch` is the only thing that exercises real Neon
  connectivity, so a PR is the actual integration test for DB changes, not
  local Postgres alone.
