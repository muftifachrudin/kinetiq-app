"""Binance USDS-M perpetual futures connector via CCXT.

First real connector (Section B.11: CCXT as the primary CEX data source).
Scope is deliberately narrow -- funding rate + OHLCV for a fixed symbol
list -- native-WS fallback, other venues, and other data types (open
interest, liquidations, orderbook) are not built yet (see ingestion README).
"""

import ccxt

FUNDING_INTERVAL_HOURS = 8  # Binance USDS-M standard; ccxt doesn't expose this uniformly


def make_exchange() -> ccxt.Exchange:
    return ccxt.binanceusdm()


def fetch_funding_rate(exchange: ccxt.Exchange, venue_symbol: str) -> dict:
    """Returns a dict with the fields ingest.py maps onto the funding_rate row."""
    data = exchange.fetch_funding_rate(venue_symbol)
    return {
        "timestamp_ms": data.get("timestamp"),
        "funding_rate": data["fundingRate"],
        "predicted_next_rate": data.get("nextFundingRate"),
        "mark_price": data.get("markPrice"),
        "funding_interval_hours": FUNDING_INTERVAL_HOURS,
    }


def fetch_ohlcv(exchange: ccxt.Exchange, venue_symbol: str, timeframe: str, limit: int) -> list[dict]:
    """Returns a list of dicts, one per candle, in the shape ingest.py expects."""
    candles = exchange.fetch_ohlcv(venue_symbol, timeframe=timeframe, limit=limit)
    return [
        {
            "timestamp_ms": ts_ms,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
        for ts_ms, open_, high, low, close, volume in candles
    ]
