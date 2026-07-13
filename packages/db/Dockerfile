# Migration runner -- a minimal, always-idle container whose only job is
# to be the target of a Coolify Scheduled Task that runs
# `alembic upgrade head` periodically. This exists to close a real gap:
# `api-gateway` used to run migrations automatically as part of its own
# Railway startCommand on every deploy, but it was deleted when Kinetiq
# narrowed scope to single-operator (apps/platform-core/*). Two migrations
# (0009, 0010) had to be applied to production by hand via the Neon
# HTTP-SQL endpoint in the meantime -- not sustainable as a long-term
# process.
#
# Deliberately NOT tied to any other application's deploy lifecycle (e.g.
# bundling this into the ingestion worker's Dockerfile) -- that would
# reproduce the exact same class of bug this fixes: if that service is
# ever deleted or replaced, migrations silently stop running again with
# no obvious signal, same as what happened when api-gateway was removed.
# A dedicated resource whose only purpose is this can't be "accidentally"
# deleted along with an unrelated service.
#
# BUILD CONTEXT MUST BE THE REPO ROOT: in Coolify, set this application's
# Base Directory to the repo root and Dockerfile Location to
# packages/db/Dockerfile.
#
# Required env var: DATABASE_URL_MIGRATIONS (the neondb_owner connection
# string -- has DDL rights, unlike the app's own least-privilege
# kinetiq_app role). packages/db/migrations/env.py already reads this
# exact env var name (falling back to DATABASE_URL if unset), no code
# change needed here.
FROM python:3.11-slim

WORKDIR /app/packages/db
COPY packages/db /app/packages/db
RUN pip install --no-cache-dir -e .

# Idle forever -- the actual `alembic upgrade head` invocation happens via
# a Coolify Scheduled Task executing inside this running container, not
# via this CMD. A container that runs once and exits isn't a valid target
# for `docker exec`-style scheduled commands.
CMD ["sleep", "infinity"]
