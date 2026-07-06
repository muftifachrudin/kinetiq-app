#!/usr/bin/env bash
# Manual Alembic migration against the real production Neon database,
# bypassing GitHub Actions entirely -- for use from MobaXterm/Termux when
# GitHub Actions is unavailable (quota exhausted, etc).
#
# NOTE this does NOT replace the automatic migration that already runs on
# every Railway deploy (railway.toml's startCommand runs
# `alembic upgrade head` before uvicorn starts, every single deploy --
# docs/deployment-runbook.md). This script is for running a migration
# standalone, e.g. to apply/test a new migration BEFORE deploying the code
# that depends on it, or to troubleshoot without a full app deploy.
#
# One-time setup: export DATABASE_URL_MIGRATIONS in your shell profile
# (~/.bashrc or ~/.zshrc on that machine -- NEVER commit this value to
# git). This must be the neondb_owner connection string (has DDL rights),
# NOT the app's least-privilege kinetiq_app role -- get it from Railway's
# Variables tab (api-gateway service) or the Neon console. Example:
#   export DATABASE_URL_MIGRATIONS="postgresql://neondb_owner:...@...neon.tech/dbname"
#
# Usage (from repo root):
#   ./scripts/manual-migrate-neon.sh          # alembic upgrade head
#   ./scripts/manual-migrate-neon.sh current  # check current revision, no changes
#   ./scripts/manual-migrate-neon.sh history  # list migration history
set -euo pipefail

if [ -z "${DATABASE_URL_MIGRATIONS:-}" ] && [ -z "${DATABASE_URL:-}" ]; then
  echo "Neither DATABASE_URL_MIGRATIONS nor DATABASE_URL is set in this shell." >&2
  echo "One-time setup: export DATABASE_URL_MIGRATIONS=\"postgresql://neondb_owner:...@...neon.tech/dbname\" in your shell profile." >&2
  exit 1
fi

if [ ! -d "packages/db" ]; then
  echo "Run this from the kinetiq-app repo root (packages/db not found here)." >&2
  exit 1
fi

ACTION="${1:-upgrade head}"

cd packages/db
echo "Running: alembic $ACTION (against $([ -n "${DATABASE_URL_MIGRATIONS:-}" ] && echo DATABASE_URL_MIGRATIONS || echo DATABASE_URL))"
python -m alembic $ACTION
