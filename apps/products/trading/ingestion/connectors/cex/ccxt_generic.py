"""Generic CCXT-based connector for CEX perpetual futures.

Started as a Binance-only module; generalized once a second venue (Bybit)
was added -- ccxt exposes the same unified fetch_funding_rate/fetch_ohlcv
API across exchanges (Bybit's fetch_funding_rate is "emulated" by ccxt
rather than a single native call, but returns the same unified shape), so
one wrapper works for any ccxt exchange id, not just Binance's.

funding_rate and ohlcv are PUBLIC endpoints on every venue supported so
far -- no API key is required to fetch them. Per-venue API key env vars
are optional and only useful for a separate, higher per-key rate limit;
they must be **read-only** keys (exchange API management -> only enable
reading/market-data permissions, never trading/withdrawals) -- this
script never places orders, so a trade-capable key here would be pure
unnecessary blast radius. PROXY_URL is shared across all venues (it
solves IP blocking/rate-limiting from cloud/datacenter IPs, a network-
level concern independent of which exchange or which API key is used).
"""

import os

import ccxt

FUNDING_INTERVAL_HOURS = 8  # standard for most USDT-margined perpetuals; ccxt doesn't expose this uniformly


def make_exchange(ccxt_id: str, api_key_env: str, api_secret_env: str) -> ccxt.Exchange:
    exchange_class = getattr(ccxt, ccxt_id)
    config = {}
    api_key = os.environ.get(api_key_env)
    api_secret = os.environ.get(api_secret_env)
    if api_key and api_secret:
        config["apiKey"] = api_key
        config["secret"] = api_secret

    exchange = exchange_class(config)

    proxy_url = os.environ.get("PROXY_URL")
    if proxy_url:
        # Only set httpsProxy, not both httpProxy and httpsProxy -- ccxt's
        # check_proxy_settings() raises InvalidProxySettings if both are set,
        # even to the identical value. Every venue here is https://.
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
