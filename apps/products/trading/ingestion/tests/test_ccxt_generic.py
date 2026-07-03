import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "connectors", "cex"))
import ccxt_generic  # noqa: E402

HOUR_MS = 3_600_000


class FakeExchange:
    """Mimics just enough of ccxt.Exchange's interface for fetch_ohlcv_range:
    fetch_ohlcv(symbol, timeframe, since, limit) paging through a fixed
    candle list, and parse_timeframe(). Records every call so pagination
    behavior (page size, cursor advancement) is directly assertable."""

    def __init__(self, candles: list[list], timeframe_seconds: int = 3600):
        self.candles = candles  # [[ts_ms, o, h, l, c, v], ...] ascending
        self.timeframe_seconds = timeframe_seconds
        self.calls: list[dict] = []

    def parse_timeframe(self, timeframe: str) -> int:
        return self.timeframe_seconds

    def fetch_ohlcv(self, symbol, timeframe=None, since=None, limit=None):
        self.calls.append({"symbol": symbol, "since": since, "limit": limit})
        page = [c for c in self.candles if since is None or c[0] >= since]
        return page[:limit]


def mk_candle(ts_ms: int) -> list:
    return [ts_ms, 100.0, 101.0, 99.0, 100.5, 10.0]


# --- fetch_ohlcv (since_ms passthrough) ---


def test_fetch_ohlcv_passes_since_ms_through():
    exchange = FakeExchange([mk_candle(0), mk_candle(HOUR_MS)])
    ccxt_generic.fetch_ohlcv(exchange, "BTC/USDT:USDT", "1h", limit=10, since_ms=HOUR_MS)
    assert exchange.calls == [{"symbol": "BTC/USDT:USDT", "since": HOUR_MS, "limit": 10}]


def test_fetch_ohlcv_defaults_since_ms_to_none():
    exchange = FakeExchange([mk_candle(0)])
    ccxt_generic.fetch_ohlcv(exchange, "BTC/USDT:USDT", "1h", limit=10)
    assert exchange.calls[0]["since"] is None


def test_fetch_ohlcv_shapes_candles_as_dicts():
    exchange = FakeExchange([mk_candle(0)])
    result = ccxt_generic.fetch_ohlcv(exchange, "BTC/USDT:USDT", "1h", limit=10)
    assert result == [{"timestamp_ms": 0, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10.0}]


# --- fetch_ohlcv_range (pagination) ---


def test_fetch_ohlcv_range_pages_across_multiple_calls():
    candles = [mk_candle(i * HOUR_MS) for i in range(10)]
    exchange = FakeExchange(candles)
    result = ccxt_generic.fetch_ohlcv_range(exchange, "BTC/USDT:USDT", "1h", since_ms=0, until_ms=9 * HOUR_MS, page_limit=3)
    assert [c["timestamp_ms"] for c in result] == [i * HOUR_MS for i in range(10)]
    # 10 candles at page_limit=3 -> 4 pages (3,3,3,1), no gaps/overlaps
    assert len(exchange.calls) == 4


def test_fetch_ohlcv_range_advances_cursor_by_timeframe_duration_not_page_size():
    candles = [mk_candle(i * HOUR_MS) for i in range(5)]
    exchange = FakeExchange(candles)
    ccxt_generic.fetch_ohlcv_range(exchange, "BTC/USDT:USDT", "1h", since_ms=0, until_ms=4 * HOUR_MS, page_limit=2)
    # page 1: since=0 -> returns ts=[0,1h], last=1h -> next cursor = 2h (1h + 1h timeframe), not 1h+something-else
    assert exchange.calls[1]["since"] == 2 * HOUR_MS


def test_fetch_ohlcv_range_stops_on_empty_page():
    candles = [mk_candle(0), mk_candle(HOUR_MS)]  # only 2 candles exist at all
    exchange = FakeExchange(candles)
    result = ccxt_generic.fetch_ohlcv_range(exchange, "BTC/USDT:USDT", "1h", since_ms=0, until_ms=100 * HOUR_MS, page_limit=10)
    assert [c["timestamp_ms"] for c in result] == [0, HOUR_MS]  # doesn't hang or fabricate candles past what's available


def test_fetch_ohlcv_range_excludes_candles_past_until_ms():
    candles = [mk_candle(i * HOUR_MS) for i in range(5)]
    exchange = FakeExchange(candles)
    result = ccxt_generic.fetch_ohlcv_range(exchange, "BTC/USDT:USDT", "1h", since_ms=0, until_ms=2 * HOUR_MS, page_limit=10)
    assert [c["timestamp_ms"] for c in result] == [0, HOUR_MS, 2 * HOUR_MS]


def test_fetch_ohlcv_range_defaults_until_ms_to_now():
    candles = [mk_candle(i * HOUR_MS) for i in range(3)]
    exchange = FakeExchange(candles)
    # since_ms far enough back that "now" (real wall clock) is well past all 3 candles
    result = ccxt_generic.fetch_ohlcv_range(exchange, "BTC/USDT:USDT", "1h", since_ms=0)
    assert len(result) == 3


# --- make_exchange ---


def test_make_exchange_enables_rate_limit():
    exchange = ccxt_generic.make_exchange("binanceusdm", None, None)
    assert exchange.enableRateLimit is True
