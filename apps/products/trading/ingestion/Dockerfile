# Ingestion worker (apps/products/trading/ingestion/worker.py) -- background
# process, not a web service (no port to expose, no healthcheck path).
#
# BUILD CONTEXT MUST BE THE REPO ROOT, not this directory: this worker
# needs the sibling packages/db package (for kinetiq_db), and Docker's COPY
# can never reach outside its build context -- same constraint Railway's
# Root Directory had, just Docker's version of it. In Coolify, set this
# application's "Base Directory" to the repo root and "Dockerfile Location"
# to apps/products/trading/ingestion/Dockerfile.
#
# Replaces railway.ingestion-worker.toml's startCommand/dependency-install
# step 1:1 -- same CLI args (see that file's history for why these
# particular --backfill-*-since-days values), same PYTHONPATH shape, same
# ingestion/requirements.txt (NOT the repo-root requirements.txt, which was
# only a Railpack single-file-detection workaround that Docker doesn't need).
#
# apps/products/trading/agent-orchestrator is ALSO copied, as a sibling of
# ingestion inside the image: signal_loop.py (--no-signals is NOT passed
# below, so this path is live) does its own sys.path.insert() at import time
# for agent-orchestrator/skills/strategy and
# agent-orchestrator/validation/fib_gann_backtest (fib_gann_timing,
# position_sizing, market_structure, htf_bias, derivatives_context,
# signal_runner, trade_simulator) relative to "../agent-orchestrator" from
# ingestion's own directory -- caught by an actual Coolify deploy attempt
# (ModuleNotFoundError: fib_gann_timing), not assumed to work from reading
# the code alone. None of that import chain touches
# fit_weights.py/gated_campaign.py (the only two files under
# agent-orchestrator that need numpy/pandas/sklearn), so this doesn't pull
# those heavier deps into the image.
FROM python:3.11-slim

WORKDIR /app

COPY packages/db /app/packages/db
COPY apps/products/trading/ingestion /app/apps/products/trading/ingestion
COPY apps/products/trading/agent-orchestrator /app/apps/products/trading/agent-orchestrator

RUN pip install --no-cache-dir -r /app/apps/products/trading/ingestion/requirements.txt

ENV PYTHONPATH=/app/packages/db/src:/app/apps/products/trading/ingestion
# Without this, Python fully buffers stdout when it isn't a TTY (always true
# under Docker) -- worker.py's print()-based progress logging would sit in
# an internal buffer and never reach `docker logs`/Coolify's log viewer
# until the buffer filled or the process exited. Caught via a real deploy:
# the container ran (and, per Coolify's app status, was even fine on some
# health axis) but its log output was completely empty.
ENV PYTHONUNBUFFERED=1
WORKDIR /app/apps/products/trading/ingestion

# Coolify's own restart policy (application Advanced settings) handles the
# "restart on exit" behavior railway.ingestion-worker.toml's
# restartPolicyType = "always" provided -- set it to "always"/"unless-stopped"
# there, not duplicated here.
CMD ["python", "-m", "worker", \
     "--venues", "binance", "bybit", \
     "--symbols", "BTC/USDT:USDT", "ETH/USDT:USDT", \
     "--backfill-15m-since-days", "1100", \
     "--backfill-funding-since-days", "90", \
     "--backfill-oi-since-days", "7"]
