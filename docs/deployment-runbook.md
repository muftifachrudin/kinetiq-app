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
  `apps/platform-core/api-gateway` in the dashboard (Settings -> Source).
- Neon project's default/primary branch is named **`production`**, not `main`.
  Git branch names and Neon branch names are two independent naming schemes --
  don't assume they match.

## Neon gotchas

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

7. **A sibling monorepo package (`-e ../../../packages/db` in
   `requirements.txt`) fails with `ERROR: ../../../packages/db is not a
   valid editable requirement`.** Railpack's native install step copies
   *only* `requirements.txt` into an isolated build layer before running
   `pip install` (a standard Docker layer-caching trick: install deps
   before copying the rest of the source, so code-only changes don't
   invalidate the dependency-install cache layer). At that point, nothing
   outside the service's own directory exists yet -- sibling directories
   like `packages/db` aren't copied in until a later step, well after
   `pip install -r requirements.txt` already ran (and failed). This means
   **pip-installing a sibling monorepo package from `requirements.txt`
   doesn't work on Railpack**, full stop -- not a path-syntax mistake, a
   structural build-order issue. Fix: don't have pip install it at all.
   Point `PYTHONPATH` at the sibling package's source directory in
   `startCommand` instead (e.g.
   `PYTHONPATH=../../../packages/db/src python -m uvicorn main:app ...`)
   so it's imported at *runtime*, by which point the full repo (including
   `packages/db`) has been copied into the container. Any future service
   that needs to reuse `packages/db`'s models should use this pattern, not
   an editable pip install.

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
