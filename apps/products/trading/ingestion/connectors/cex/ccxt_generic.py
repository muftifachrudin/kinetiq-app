"""Generic CCXT-based connector for CEX/DEX-perp venues.

Started as a Binance-only module; generalized once a second venue (Bybit)
was added -- ccxt exposes the same unified fetch_funding_rate/fetch_ohlcv
API across exchanges (Bybit's fetch_funding_rate is "emulated" by ccxt
rather than a single native call, but returns the same unified shape), so
one wrapper works for any ccxt exchange id, not just Binance's.

Hyperliquid (first DEX-perp venue added) breaks that assumption in two
ways ccxt's `exchange.has` flags directly: (1) `fetchFundingRate` is
False -- only the plural, all-market `fetchFundingRates` exists, so
fetch_funding_rate() below falls back to it and picks out the one symbol
requested; (2) its auth credentials are `walletAddress`/`privateKey`, not
`apiKey`/`secret` -- irrelevant here anyway since funding_rate/ohlcv are
public endpoints on every venue supported so far (no key needed), so
`api_key_env`/`api_secret_env` are simply None for Hyperliquid in
ingest.py's VENUES rather than pointing at env vars ccxt would silently
ignore.

Per-venue API key env vars (CEX venues only) are optional and only useful
for a separate, higher per-key rate limit; they must be **read-only** keys
(exchange API management -> only enable reading/market-data permissions,
never trading/withdrawals) -- this script never places orders, so a
trade-capable key here would be pure unnecessary blast radius. PROXY_URL
is shared across all venues (it solves IP blocking/rate-limiting from
cloud/datacenter IPs, a network-level concern independent of which
exchange or which API key is used).
"""

import os
from datetime import datetime, timezone

import ccxt

# Fallback only, used when a venue's funding_rate response doesn't include
# an `interval` field. Prefer the real per-venue value below -- it isn't
# uniformly 8h: Hyperliquid funding settles hourly ('1h'), and even
# Binance/Bybit report per-symbol values (mostly '8h', but not always)
# rather than a fixed platform-wide constant.
DEFAULT_FUNDING_INTERVAL_HOURS = 8


def make_exchange(ccxt_id: str, api_key_env: str | None, api_secret_env: str | None) -> ccxt.Exchange:
    exchange_class = getattr(ccxt, ccxt_id)
    config = {"enableRateLimit": True}  # ccxt self-throttles to the exchange's own rateLimit (ms) before every call -- was unset, meaning nothing protected a backfill loop from tripping 429s
    if api_key_env and api_secret_env:
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
    if exchange.has.get("fetchFundingRate"):
        data = exchange.fetch_funding_rate(venue_symbol)
    else:
        # e.g. Hyperliquid: no single-symbol call, only the all-market
        # plural -- same unified per-symbol shape once indexed by symbol.
        data = exchange.fetch_funding_rates([venue_symbol])[venue_symbol]

    interval = data.get("interval")  # e.g. "8h", "1h" -- or None if the venue doesn't report it
    funding_interval_hours = int(interval[:-1]) if interval else DEFAULT_FUNDING_INTERVAL_HOURS

    return {
        "timestamp_ms": data.get("timestamp"),
        "funding_rate": data["fundingRate"],
        "predicted_next_rate": data.get("nextFundingRate"),
        "mark_price": data.get("markPrice"),
        "funding_interval_hours": funding_interval_hours,
    }


def _candle_dicts(candles: list) -> list[dict]:
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


def fetch_ohlcv(exchange: ccxt.Exchange, venue_symbol: str, timeframe: str, limit: int, since_ms: int | None = None) -> list[dict]:
    """Returns a list of dicts, one per candle, in the shape ingest.py expects.
    since_ms=None (the default, used by the existing latest-N live path)
    means "most recent `limit` candles" -- ccxt's own default behavior when
    `since` isn't passed."""
    candles = exchange.fetch_ohlcv(venue_symbol, timeframe=timeframe, limit=limit, since=since_ms)
    return _candle_dicts(candles)


def fetch_ohlcv_range(
    exchange: ccxt.Exchange,
    venue_symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int | None = None,
    page_limit: int = 1000,
) -> list[dict]:
    """Pages forward from since_ms to until_ms (default: now) collecting
    every candle in between -- ingest.py's existing fetch_ohlcv() only ever
    asks for "the latest N candles," which can't backfill history at all.
    Advances by the timeframe's own duration (ccxt.Exchange.parse_timeframe,
    reused rather than reimplemented) after each page so pages never overlap
    and never skip a candle. Stops when a page comes back empty (exchange
    has no more candles, e.g. before the symbol was listed) or once a page's
    last candle reaches until_ms -- whichever happens first. Rate limiting
    is handled by make_exchange()'s enableRateLimit=True, not by an explicit
    sleep here; ccxt paces every call to exchange.fetch_ohlcv() internally,
    which is why this can page through months of history in seconds without
    tripping a 429 while still being about as fast as the exchange allows."""
    if until_ms is None:
        until_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    timeframe_ms = exchange.parse_timeframe(timeframe) * 1000

    all_candles: list[dict] = []
    cursor_ms = since_ms
    while cursor_ms <= until_ms:
        page = exchange.fetch_ohlcv(venue_symbol, timeframe=timeframe, since=cursor_ms, limit=page_limit)
        if not page:
            break
        all_candles.extend(_candle_dicts(page))
        cursor_ms = page[-1][0] + timeframe_ms

    return [c for c in all_candles if c["timestamp_ms"] <= until_ms]
