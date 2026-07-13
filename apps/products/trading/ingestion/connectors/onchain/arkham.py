"""Arkham Intel API connector -- entity exchange flow only (collect-only,
see migration 0010's docstring for why this isn't wired into signal
scoring yet).

Auth: `API-Key: <key>` header (not `Authorization: Bearer`, confirmed
against the real API's docs before writing this). Public credit cost is
low (3 credits/call for /flow/entity/{entity}) and rate limit is generous
(20 req/s standard tier) -- polling a handful of major CEX entities every
few hours is nowhere near either limit.

GET /flow/entity/{entity}?chains=bitcoin returns USD in/outflow between
the named entity (e.g. "binance") and the rest of the chain, as an object
keyed by chain name, each a list of {time, inflow, outflow,
cumulativeInflow, cumulativeOutflow} records -- fetch_entity_flow() does
the HTTP call, parse_entity_flow() reshapes the response into flat records
matching kinetiq_db.models.OnchainExchangeFlow's columns, kept separate so
the reshaping logic is unit-testable against a fixture response without a
real API call (same fetch/parse split as connectors/cex/ccxt_generic.py).
"""

from datetime import datetime, timezone

import requests

ARKHAM_BASE_URL = "https://api.arkm.com"


def fetch_entity_flow(entity: str, chains: list[str], api_key: str) -> dict:
    response = requests.get(
        f"{ARKHAM_BASE_URL}/flow/entity/{entity}",
        params={"chains": ",".join(chains)},
        headers={"API-Key": api_key},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def parse_entity_flow(entity: str, raw: dict) -> list[dict]:
    """Pure -- flattens {chain: [records]} into one list of dicts shaped
    for OnchainExchangeFlow, one dict per (chain, time) data point.
    `time` is parsed as ISO 8601 (Arkham's stated format); a `Z` suffix is
    normalized to `+00:00` since Python's fromisoformat() before 3.11
    doesn't accept a bare `Z` -- kept even though this repo targets 3.11+,
    since it costs nothing and removes any doubt.

    `source` is set explicitly here rather than left to the model's
    `server_default="arkham"` -- SQLAlchemy's `db.merge()` (used by
    ingest_onchain.py for idempotent upsert) decides INSERT vs UPDATE
    from the Python-side primary-key values *before* flush, and a
    server_default only ever resolves in Postgres at INSERT time. Leaving
    `source` unset on the object made merge() treat every row as new on
    every run (never matching the existing composite PK), which surfaced
    as a real `UniqueViolation` on a second run against a real Postgres --
    caught by actually re-running the script, not by reading the code."""
    records = []
    for chain, points in raw.items():
        for point in points:
            ts_str = point["time"].replace("Z", "+00:00")
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            records.append(
                {
                    "source": "arkham",
                    "entity": entity,
                    "chain": chain,
                    "ts": ts,
                    "inflow_usd": point.get("inflow"),
                    "outflow_usd": point.get("outflow"),
                    "cumulative_inflow_usd": point.get("cumulativeInflow"),
                    "cumulative_outflow_usd": point.get("cumulativeOutflow"),
                }
            )
    return records
