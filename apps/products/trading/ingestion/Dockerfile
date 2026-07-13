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
FROM python:3.11-slim

WORKDIR /app

COPY packages/db /app/packages/db
COPY apps/products/trading/ingestion /app/apps/products/trading/ingestion

RUN pip install --no-cache-dir -r /app/apps/products/trading/ingestion/requirements.txt

ENV PYTHONPATH=/app/packages/db/src:/app/apps/products/trading/ingestion
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
