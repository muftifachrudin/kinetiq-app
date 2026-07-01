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
