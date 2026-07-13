"""Entrypoint: fetch BTC exchange in/outflow from Arkham Intel API
(connectors/onchain/arkham.py) and upsert into Neon. Collect-only (see
migration 0010's docstring) -- standalone script, not wired into
signal_loop.py or any confidence scoring. Run manually or via cron; no
tight polling cadence needed since Arkham's flow data points are not
sub-hourly (unlike ohlcv/funding_rate), so this doesn't need worker.py's
continuous poll-loop treatment.

Usage:
    python3 ingest_onchain.py --entities binance coinbase okx bybit kraken --chains bitcoin
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "connectors", "onchain"))

import arkham  # noqa: E402
from kinetiq_db.engine import normalize_db_url  # noqa: E402
from kinetiq_db.models import OnchainExchangeFlow  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

DEFAULT_ENTITIES = ["binance", "coinbase", "okx", "bybit", "kraken"]
DEFAULT_CHAINS = ["bitcoin"]


def get_session() -> Session:
    engine = create_engine(normalize_db_url(os.environ["DATABASE_URL"]), pool_pre_ping=True, pool_recycle=300)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def ingest_entity_flow(db: Session, entity: str, chains: list[str], api_key: str) -> int:
    """Fetches + upserts one entity's flow records, returns rows written."""
    raw = arkham.fetch_entity_flow(entity, chains, api_key)
    records = arkham.parse_entity_flow(entity, raw)
    for record in records:
        db.merge(OnchainExchangeFlow(**record))
    db.commit()
    return len(records)


def run(entities: list[str], chains: list[str], api_key: str) -> None:
    db = get_session()
    for entity in entities:
        try:
            written = ingest_entity_flow(db, entity, chains, api_key)
            print(f"[{entity}] onchain_exchange_flow OK ({written} records, chains={chains})")
        except Exception as exc:
            db.rollback()
            print(f"[{entity}] onchain_exchange_flow FAILED: {exc}")
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entities", nargs="+", default=DEFAULT_ENTITIES)
    parser.add_argument("--chains", nargs="+", default=DEFAULT_CHAINS)
    args = parser.parse_args()

    key = os.environ.get("ARKHAM_API_KEY")
    if not key:
        sys.exit("ARKHAM_API_KEY is not set")

    run(args.entities, args.chains, key)
