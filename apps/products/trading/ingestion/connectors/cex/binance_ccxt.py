"""Binance USDS-M perpetual futures connector via CCXT.

First real connector (Section B.11: CCXT as the primary CEX data source).
Scope is deliberately narrow -- funding rate + OHLCV for a fixed symbol
list -- native-WS fallback, other venues, and other data types (open
interest, liquidations, orderbook) are not built yet (see ingestion README).

funding_rate and ohlcv are both PUBLIC Binance endpoints -- no API key is
required to fetch them. BINANCE_API_KEY/BINANCE_API_SECRET are optional
and only useful for a separate, higher per-key rate limit; they must be a
**read-only** key (Binance API Management -> create key -> leave "Enable
Trading"/"Enable Futures"/"Enable Withdrawals" all unchecked, only
"Enable Reading" on) -- this script never places orders, so a
trade-capable key here would be pure unnecessary blast radius.
BINANCE_PROXY_URL is separate from the API key and solves a different
problem (Binance blocking/rate-limiting requests from certain cloud/
datacenter IPs, e.g. Railway's) -- an authenticated request from a
blocked IP is still blocked; only routing through an allowed IP (e.g. a
residential/datacenter proxy like Webshare.io) fixes that.
"""

import os

import ccxt

FUNDING_INTERVAL_HOURS = 8  # Binance USDS-M standard; ccxt doesn't expose this uniformly


def make_exchange() -> ccxt.Exchange:
    config = {}
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    if api_key and api_secret:
        config["apiKey"] = api_key
        config["secret"] = api_secret

    exchange = ccxt.binanceusdm(config)

    proxy_url = os.environ.get("BINANCE_PROXY_URL")
    if proxy_url:
        # Only set httpsProxy, not both -- ccxt's check_proxy_settings() raises
        # InvalidProxySettings("...multiple conflicting proxy settings...") if
        # httpProxy and httpsProxy are both set, even to the identical value.
        # Binance's API is always https://, so httpsProxy is the one that
        # actually matters (it's keyed off the target URL's scheme, not the
        # proxy server's own transport).
        exchange.httpsProxy = proxy_url

    return exchange


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
