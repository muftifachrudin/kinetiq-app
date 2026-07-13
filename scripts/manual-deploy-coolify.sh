#!/usr/bin/env bash
# Manual Coolify deploy trigger, bypassing GitHub Actions entirely -- for use
# from MobaXterm (Windows), Termux (Android), or a laptop shell when GitHub
# Actions is unavailable, or to redeploy without waiting for a git push.
#
# NOTE this does NOT replace Coolify's own native GitHub auto-deploy (each
# application's git source, connected directly to this repo) -- that already
# deploys on every push to the configured branch regardless of GitHub Actions
# status, since it's Coolify's own webhook, not a GitHub Actions workflow
# (docs/deployment-runbook.md). This script is for:
#   (a) triggering a redeploy of the CURRENT branch tip without a new push,
#   (b) a manual trigger if the git-push auto-deploy webhook itself is ever
#       stuck/delayed.
#
# One-time setup: export COOLIFY_URL and COOLIFY_TOKEN in your shell profile
# (~/.bashrc or ~/.zshrc -- NEVER commit these values to git). Get a token
# from Coolify -> Security -> API Tokens (read+write+deploy permissions,
# not root). Example:
#   export COOLIFY_URL="https://<your-coolify-host>"
#   export COOLIFY_TOKEN="1|xxxxxxxxxxxx"
#
# Usage (from repo root):
#   ./scripts/manual-deploy-coolify.sh <application-uuid>
# Find the UUID via: python tools/coolify_logs.py (no args, lists all -- the
# deploy endpoint itself only accepts the UUID, not the application name).
set -euo pipefail

APP_UUID="${1:-}"
if [ -z "$APP_UUID" ]; then
  echo "Usage: $0 <application-uuid>" >&2
  echo "List applications (with their UUIDs): python tools/coolify_logs.py" >&2
  exit 1
fi

if [ -z "${COOLIFY_URL:-}" ] || [ -z "${COOLIFY_TOKEN:-}" ]; then
  echo "COOLIFY_URL and COOLIFY_TOKEN must both be set." >&2
  exit 1
fi

echo "Triggering deploy for '$APP_UUID'..."
curl -sS -H "Authorization: Bearer $COOLIFY_TOKEN" "$COOLIFY_URL/api/v1/deploy?uuid=$APP_UUID"
echo
echo "Poll status: python tools/coolify_logs.py --app $APP_UUID --logs build"
