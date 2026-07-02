"""Native REST fallback for Binance/Bybit (docs/prd.md Section B.11: native
exchange REST is the documented fallback once the primary ccxt-layer path
fails repeatedly). Only Binance and Bybit -- the two CEX venues B.11 names
for this -- have one here. Hyperliquid doesn't: its ccxt connector already
calls api.hyperliquid.xyz directly with no separate SDK/vendor layer in
between (confirmed while adding the Hyperliquid connector), so there's no
distinct "native" path left to fall back to for it.

This protects against ccxt-library-level issues (a bug, a breaking change
in a new ccxt release, a client-side parsing regression), not exchange-side
outages -- both paths hit the same exchange servers, so if Binance/Bybit
itself is down neither will work. Returns the same unified dict shape
ccxt_generic.fetch_funding_rate/fetch_ohlcv do, so ingest.py's DB-writing
code doesn't need to know or care which path supplied the data.

Reads the same PROXY_URL env var ccxt_generic.py does, for the same reason
(IP-level blocking of exchange endpoints from cloud/datacenter IPs, and
apparently also from at least some Indonesian mobile carriers -- confirmed
live: fapi.binance.com fails with a certificate hostname mismatch even via
plain `curl`, not a Python/certifi issue, from a Termux/Android test on a
regular Indonesian mobile network). Without this, the fallback would hit
the exact same IP-blocked path ccxt already failed on, defeating its whole
purpose in that scenario specifically -- a bug found via that live test,
not theorized upfront.
"""

import os

import requests

BINANCE_FAPI = "https://fapi.binance.com"
BYBIT_API = "https://api.bybit.com"

REQUEST_TIMEOUT_SECONDS = 10

_BYBIT_TIMEFRAME_MAP = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240", "6h": "360", "12h": "720",
    "1d": "D", "1w": "W", "1M": "M",
}


def _native_symbol(venue_symbol: str) -> str:
    """'BTC/USDT:USDT' -> 'BTCUSDT' -- both Binance USDS-M and Bybit linear
    use base+quote concatenated with no separator, no settle suffix."""
    base = venue_symbol.split("/")[0]
    quote = venue_symbol.split(":")[-1]
    return base + quote


def _proxies() -> dict:
    proxy_url = os.environ.get("PROXY_URL")
    return {"https": proxy_url} if proxy_url else {}


def binance_funding_rate(venue_symbol: str) -> dict:
    resp = requests.get(
        f"{BINANCE_FAPI}/fapi/v1/premiumIndex",
        params={"symbol": _native_symbol(venue_symbol)},
        timeout=REQUEST_TIMEOUT_SECONDS,
        proxies=_proxies(),
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "timestamp_ms": data["time"],
        "funding_rate": float(data["lastFundingRate"]),
        "predicted_next_rate": None,
        "mark_price": float(data["markPrice"]),
        # premiumIndex doesn't expose the funding interval directly, unlike
        # ccxt's unified fetch_funding_rate -- matches ccxt_generic.py's own
        # DEFAULT_FUNDING_INTERVAL_HOURS fallback for the same reason.
        "funding_interval_hours": 8,
    }


def binance_ohlcv(venue_symbol: str, timeframe: str, limit: int) -> list[dict]:
    resp = requests.get(
        f"{BINANCE_FAPI}/fapi/v1/klines",
        params={"symbol": _native_symbol(venue_symbol), "interval": timeframe, "limit": limit},
        timeout=REQUEST_TIMEOUT_SECONDS,
        proxies=_proxies(),
    )
    resp.raise_for_status()
    return [
        {
            "timestamp_ms": row[0],
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in resp.json()
    ]


def bybit_funding_rate(venue_symbol: str) -> dict:
    resp = requests.get(
        f"{BYBIT_API}/v5/market/tickers",
        params={"category": "linear", "symbol": _native_symbol(venue_symbol)},
        timeout=REQUEST_TIMEOUT_SECONDS,
        proxies=_proxies(),
    )
    resp.raise_for_status()
    data = resp.json()
    ticker = data["result"]["list"][0]
    return {
        "timestamp_ms": int(data["time"]),
        "funding_rate": float(ticker["fundingRate"]),
        "predicted_next_rate": None,
        "mark_price": float(ticker["markPrice"]),
        "funding_interval_hours": 8,
    }


def bybit_ohlcv(venue_symbol: str, timeframe: str, limit: int) -> list[dict]:
    resp = requests.get(
        f"{BYBIT_API}/v5/market/kline",
        params={
            "category": "linear",
            "symbol": _native_symbol(venue_symbol),
            "interval": _BYBIT_TIMEFRAME_MAP.get(timeframe, "60"),
            "limit": limit,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
        proxies=_proxies(),
    )
    resp.raise_for_status()
    rows = resp.json()["result"]["list"]  # Bybit returns newest-first, ccxt convention is oldest-first
    return [
        {
            "timestamp_ms": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in reversed(rows)
    ]


# ingest.py looks up FALLBACKS[venue_name][data_type] -- absent entries
# (e.g. "hyperliquid") mean no native fallback exists for that venue.
FALLBACKS = {
    "binance": {"funding_rate": binance_funding_rate, "ohlcv": binance_ohlcv},
    "bybit": {"funding_rate": bybit_funding_rate, "ohlcv": bybit_ohlcv},
}
