"""Design brief Section 6: data_loader.py -- loads historical OHLCV
candles from the production DB for backtesting. Reuses the same
kinetiq_db models/connection pattern as apps/products/trading/ingestion/
ingest.py (create_engine(normalize_db_url(...))), read-only, no live
exchange calls -- ingestion owns writing candles into the DB, this module
only ever reads them back out for signal_runner.py to walk over.

Not covered by this repo's pytest suite (like ingest.py, this needs a
real DATABASE_URL and real data) -- verified by running against
production directly. See docs/prd.md's Fase 2 status for the manual
verification trail of this round's wiring.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "strategy"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "packages", "db", "src"))

import fib_gann_timing as fgt  # noqa: E402
from kinetiq_db.engine import normalize_db_url  # noqa: E402
from kinetiq_db.models import Instrument, Ohlcv, Venue  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402


def load_candles(venue: str, symbol: str, timeframe: str, limit: int = 1000) -> list[fgt.Candle]:
    """Most recent `limit` candles for one instrument, oldest first (the
    order every function in fib_gann_timing.py expects)."""
    engine = create_engine(normalize_db_url(os.environ["DATABASE_URL"]))
    query = (
        select(Ohlcv.ts, Ohlcv.open, Ohlcv.high, Ohlcv.low, Ohlcv.close, Ohlcv.volume)
        .join(Instrument, Instrument.id == Ohlcv.instrument_id)
        .join(Venue, Venue.id == Instrument.venue_id)
        .where(Venue.name == venue, Instrument.symbol == symbol, Ohlcv.timeframe == timeframe)
        .order_by(Ohlcv.ts.desc())
        .limit(limit)
    )
    with engine.connect() as conn:
        rows = list(conn.execute(query))
    rows.reverse()
    return [
        fgt.Candle(
            ts=row.ts,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in rows
    ]
