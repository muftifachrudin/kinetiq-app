"""Entrypoint: fetch funding rate + OHLCV from one or more CEX venues (via
the connector in connectors/cex/ccxt_generic.py) and upsert into Neon.
Standalone script for now -- not yet wired into Inngest scheduling, which
doesn't exist in this repo yet (Section B.1/B.9). Run manually or via cron
until then.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "connectors", "cex"))

import ccxt_generic  # noqa: E402
from kinetiq_db.engine import normalize_db_url  # noqa: E402
from kinetiq_db.models import DataSourceHealth, FundingRate, Instrument, Ohlcv, Venue  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

# Adding a new venue: it must be supported by ccxt with fetch_funding_rate
# (or fetch_funding_rates, see ccxt_generic.py) + fetch_ohlcv. venue_type
# must match the `ck_venue_type` DB constraint ('cex' or 'dex'). API key env
# vars follow the "<VENUE>_API_KEY"/"<VENUE>_API_SECRET" pattern for venues
# that authenticate that way (CEX venues) -- use None/None for venues that
# don't (e.g. Hyperliquid uses walletAddress/privateKey instead, moot here
# since this script only calls public endpoints).
VENUES = {
    "binance": {
        "ccxt_id": "binanceusdm",
        "venue_type": "cex",
        "api_key_env": "BINANCE_API_KEY",
        "api_secret_env": "BINANCE_API_SECRET",
    },
    "bybit": {
        "ccxt_id": "bybit",
        "venue_type": "cex",
        "api_key_env": "BYBIT_API_KEY",
        "api_secret_env": "BYBIT_API_SECRET",
    },
    "hyperliquid": {
        "ccxt_id": "hyperliquid",
        "venue_type": "dex",
        "api_key_env": None,
        "api_secret_env": None,
    },
}


def get_session() -> Session:
    engine = create_engine(normalize_db_url(os.environ["DATABASE_URL"]))
    return sessionmaker(bind=engine)()


def upsert_venue(db: Session, venue_name: str, venue_type: str) -> Venue:
    venue = db.query(Venue).filter_by(name=venue_name).one_or_none()
    if venue is None:
        venue = Venue(name=venue_name, venue_type=venue_type)
        db.add(venue)
        db.flush()
    return venue


def upsert_instrument(db: Session, venue: Venue, market: dict) -> Instrument:
    venue_symbol = market["symbol"]
    instrument = (
        db.query(Instrument).filter_by(venue_id=venue.id, venue_symbol=venue_symbol).one_or_none()
    )
    if instrument is None:
        instrument = Instrument(
            venue_id=venue.id,
            symbol=venue_symbol,
            venue_symbol=venue_symbol,
            base_asset=market["base"],
            quote_asset=market["quote"],
            contract_type="perpetual",
        )
        db.add(instrument)
        db.flush()
    return instrument


def record_health(db: Session, venue: Venue, data_type: str, success: bool) -> None:
    health = db.query(DataSourceHealth).filter_by(venue_id=venue.id, data_type=data_type).one_or_none()
    if health is None:
        health = DataSourceHealth(venue_id=venue.id, data_type=data_type, consecutive_failures=0)
        db.add(health)
    now = datetime.now(timezone.utc)
    if success:
        health.last_success_at = now
        health.consecutive_failures = 0
    else:
        health.last_failure_at = now
        health.consecutive_failures = (health.consecutive_failures or 0) + 1
    db.commit()


def _ts(timestamp_ms: int | None) -> datetime:
    if timestamp_ms is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def ingest_funding_rate(db: Session, exchange, instrument: Instrument, venue_symbol: str) -> None:
    data = ccxt_generic.fetch_funding_rate(exchange, venue_symbol)
    db.merge(
        FundingRate(
            instrument_id=instrument.id,
            ts=_ts(data["timestamp_ms"]),
            funding_rate=data["funding_rate"],
            predicted_next_rate=data["predicted_next_rate"],
            funding_interval_hours=data["funding_interval_hours"],
            mark_price=data["mark_price"],
        )
    )
    db.commit()


def ingest_ohlcv(
    db: Session, exchange, instrument: Instrument, venue_symbol: str, timeframe: str, limit: int
) -> None:
    for candle in ccxt_generic.fetch_ohlcv(exchange, venue_symbol, timeframe, limit):
        db.merge(
            Ohlcv(
                instrument_id=instrument.id,
                timeframe=timeframe,
                ts=_ts(candle["timestamp_ms"]),
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
            )
        )
    db.commit()


def run(venue_names: list[str], symbols: list[str], timeframe: str, limit: int) -> None:
    db = get_session()

    for venue_name in venue_names:
        cfg = VENUES[venue_name]
        exchange = ccxt_generic.make_exchange(cfg["ccxt_id"], cfg["api_key_env"], cfg["api_secret_env"])
        exchange.load_markets()
        venue = upsert_venue(db, venue_name, cfg["venue_type"])
        db.commit()

        for venue_symbol in symbols:
            market = exchange.market(venue_symbol)
            instrument = upsert_instrument(db, venue, market)
            db.commit()

            try:
                ingest_funding_rate(db, exchange, instrument, venue_symbol)
                record_health(db, venue, "funding_rate", success=True)
                print(f"[{venue_name}:{venue_symbol}] funding_rate OK")
            except Exception as exc:
                db.rollback()
                record_health(db, venue, "funding_rate", success=False)
                print(f"[{venue_name}:{venue_symbol}] funding_rate FAILED: {exc}")

            try:
                ingest_ohlcv(db, exchange, instrument, venue_symbol, timeframe, limit)
                record_health(db, venue, "ohlcv", success=True)
                print(f"[{venue_name}:{venue_symbol}] ohlcv OK")
            except Exception as exc:
                db.rollback()
                record_health(db, venue, "ohlcv", success=False)
                print(f"[{venue_name}:{venue_symbol}] ohlcv FAILED: {exc}")

    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venues", nargs="+", choices=list(VENUES), default=["binance", "bybit"])
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTC/USDT:USDT", "ETH/USDT:USDT"],
        help=(
            "Same symbol list is used for every --venues entry in this run "
            "-- venues with a different quote currency (e.g. hyperliquid's "
            "USDC-quoted perps, 'BTC/USDC:USDC') must be run as a separate "
            "invocation, not mixed with binance/bybit's USDT-quoted default."
        ),
    )
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    run(args.venues, args.symbols, args.timeframe, args.limit)
