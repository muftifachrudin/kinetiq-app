"""Entrypoint: fetch funding rate + OHLCV from Binance (via the connector in
connectors/cex/binance_ccxt.py) and upsert into Neon. Standalone script for
now -- not yet wired into Inngest scheduling, which doesn't exist in this
repo yet (Section B.1/B.9). Run manually or via cron until then.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "connectors", "cex"))

import binance_ccxt  # noqa: E402
from kinetiq_db.engine import normalize_db_url  # noqa: E402
from kinetiq_db.models import DataSourceHealth, FundingRate, Instrument, Ohlcv, Venue  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

VENUE_NAME = "binance"


def get_session() -> Session:
    engine = create_engine(normalize_db_url(os.environ["DATABASE_URL"]))
    return sessionmaker(bind=engine)()


def upsert_venue(db: Session) -> Venue:
    venue = db.query(Venue).filter_by(name=VENUE_NAME).one_or_none()
    if venue is None:
        venue = Venue(name=VENUE_NAME, venue_type="cex")
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


def ingest_funding_rate(db: Session, exchange, venue: Venue, instrument: Instrument, venue_symbol: str) -> None:
    data = binance_ccxt.fetch_funding_rate(exchange, venue_symbol)
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
    for candle in binance_ccxt.fetch_ohlcv(exchange, venue_symbol, timeframe, limit):
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


def run(symbols: list[str], timeframe: str, limit: int) -> None:
    exchange = binance_ccxt.make_exchange()
    exchange.load_markets()
    db = get_session()
    venue = upsert_venue(db)
    db.commit()

    for venue_symbol in symbols:
        market = exchange.market(venue_symbol)
        instrument = upsert_instrument(db, venue, market)
        db.commit()

        try:
            ingest_funding_rate(db, exchange, venue, instrument, venue_symbol)
            record_health(db, venue, "funding_rate", success=True)
            print(f"[{venue_symbol}] funding_rate OK")
        except Exception as exc:
            db.rollback()
            record_health(db, venue, "funding_rate", success=False)
            print(f"[{venue_symbol}] funding_rate FAILED: {exc}")

        try:
            ingest_ohlcv(db, exchange, instrument, venue_symbol, timeframe, limit)
            record_health(db, venue, "ohlcv", success=True)
            print(f"[{venue_symbol}] ohlcv OK")
        except Exception as exc:
            db.rollback()
            record_health(db, venue, "ohlcv", success=False)
            print(f"[{venue_symbol}] ohlcv FAILED: {exc}")

    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["BTC/USDT:USDT", "ETH/USDT:USDT"])
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    run(args.symbols, args.timeframe, args.limit)
