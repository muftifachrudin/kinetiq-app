#!/usr/bin/env bash
# Manual Railway deploy, bypassing GitHub Actions entirely -- for use from
# MobaXterm (Windows) or Termux (Android) when GitHub Actions minutes are
# exhausted (Settings -> Billing -> Actions) or CI is otherwise unavailable.
#
# NOTE this does NOT replace Railway's own native GitHub auto-deploy
# (Settings -> Source in the Railway dashboard, connected directly to this
# repo) -- that already deploys on every push to `main` regardless of
# GitHub Actions status, since it's a separate native integration, not a
# GitHub Actions workflow (docs/deployment-runbook.md). This script is for:
#   (a) deploying local/uncommitted changes without pushing to git first,
#   (b) deploying a feature branch without merging to main,
#   (c) a manual trigger if the git-push auto-deploy webhook itself is
#       ever stuck/delayed.
#
# One-time setup (run once per machine, e.g. once in MobaXterm and once in
# Termux if you use both):
#   1. Install Railway CLI:
#        npm install -g @railway/cli
#      (needs Node.js -- MobaXterm: install via nvm-windows or Node's own
#      Windows installer first; Termux: `pkg install nodejs` first)
#   2. railway login          (opens a browser to authenticate)
#   3. cd <repo root> && railway link
#      (interactive picker -- select this project, and pick the specific
#      service when prompted: api-gateway or ingestion-worker)
#
# Usage (from repo root):
#   ./scripts/manual-deploy-railway.sh api-gateway
#   ./scripts/manual-deploy-railway.sh ingestion-worker
set -euo pipefail

SERVICE="${1:-}"
if [ -z "$SERVICE" ]; then
  echo "Usage: $0 <api-gateway|ingestion-worker>" >&2
  exit 1
fi

if ! command -v railway >/dev/null 2>&1; then
  echo "railway CLI not found. One-time setup: npm install -g @railway/cli && railway login && railway link" >&2
  exit 1
fi

if [ ! -f "railway.toml" ] && [ ! -f "railway.ingestion-worker.toml" ]; then
  echo "Run this from the kinetiq-app repo root (railway.toml not found here)." >&2
  exit 1
fi

echo "Deploying service '$SERVICE' to Railway (uploads the current working tree, uncommitted changes included)..."
railway up --service "$SERVICE"
echo "Done. Check deploy status: railway logs --service $SERVICE"
