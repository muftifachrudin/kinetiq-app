import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "connectors", "cex"))
import ccxt_generic  # noqa: E402

HOUR_MS = 3_600_000


class FakeExchange:
    """Mimics just enough of ccxt.Exchange's interface for fetch_ohlcv_range/
    fetch_funding_rate_history_range/fetch_open_interest_history_range:
    fetch_ohlcv(symbol, timeframe, since, limit) paging through a fixed
    candle list, fetch_funding_rate_history/fetch_open_interest_history
    paging through their own fixed record lists, and parse_timeframe().
    Records every call so pagination behavior (page size, cursor
    advancement) is directly assertable."""

    def __init__(self, candles: list[list] | None = None, timeframe_seconds: int = 3600, funding_records=None, oi_records=None):
        self.candles = candles or []  # [[ts_ms, o, h, l, c, v], ...] ascending
        self.timeframe_seconds = timeframe_seconds
        self.funding_records = funding_records or []  # [{"timestamp": ..., "fundingRate": ...}, ...] ascending
        self.oi_records = oi_records or []  # [{"timestamp": ..., "openInterestAmount": ...}, ...] ascending
        self.calls: list[dict] = []
        self.funding_calls: list[dict] = []
        self.oi_calls: list[dict] = []
        self.oi_snapshot: dict | None = None

    def parse_timeframe(self, timeframe: str) -> int:
        return self.timeframe_seconds

    def fetch_ohlcv(self, symbol, timeframe=None, since=None, limit=None):
        self.calls.append({"symbol": symbol, "since": since, "limit": limit})
        page = [c for c in self.candles if since is None or c[0] >= since]
        return page[:limit]

    def fetch_funding_rate_history(self, symbol, since=None, limit=None):
        self.funding_calls.append({"symbol": symbol, "since": since, "limit": limit})
        page = [r for r in self.funding_records if since is None or r["timestamp"] >= since]
        return page[:limit]

    def fetch_open_interest(self, symbol):
        return self.oi_snapshot

    def fetch_open_interest_history(self, symbol, timeframe=None, since=None, limit=None):
        self.oi_calls.append({"symbol": symbol, "timeframe": timeframe, "since": since, "limit": limit})
        page = [r for r in self.oi_records if since is None or r["timestamp"] >= since]
        return page[:limit]


def mk_candle(ts_ms: int) -> list:
    return [ts_ms, 100.0, 101.0, 99.0, 100.5, 10.0]


def mk_funding_record(ts_ms: int, rate: float = 0.0001) -> dict:
    return {"timestamp": ts_ms, "fundingRate": rate}


def mk_oi_record(ts_ms: int, amount: float = 1000.0, value: float | None = None) -> dict:
    return {"timestamp": ts_ms, "openInterestAmount": amount, "openInterestValue": value}


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


# --- fetch_funding_rate_history_range (F0e P2, pagination) ---


def test_fetch_funding_rate_history_range_pages_across_multiple_calls():
    records = [mk_funding_record(i * HOUR_MS) for i in range(10)]
    exchange = FakeExchange(funding_records=records)
    result = ccxt_generic.fetch_funding_rate_history_range(exchange, "BTC/USDT:USDT", since_ms=0, until_ms=9 * HOUR_MS, page_limit=3)
    assert [r["timestamp_ms"] for r in result] == [i * HOUR_MS for i in range(10)]
    assert len(exchange.funding_calls) == 4  # 10 records at page_limit=3 -> 4 pages, same shape as OHLCV paging


def test_fetch_funding_rate_history_range_advances_cursor_past_last_record_not_by_fixed_duration():
    # unlike OHLCV, funding history has no fixed timeframe -- cursor must
    # advance to (last record's timestamp + 1ms), not a parsed duration.
    records = [mk_funding_record(0), mk_funding_record(HOUR_MS)]
    exchange = FakeExchange(funding_records=records)
    ccxt_generic.fetch_funding_rate_history_range(exchange, "BTC/USDT:USDT", since_ms=0, until_ms=HOUR_MS, page_limit=1)
    assert exchange.funding_calls[1]["since"] == 1  # last ts (0) + 1ms, not 0 + timeframe_seconds


def test_fetch_funding_rate_history_range_shapes_records():
    exchange = FakeExchange(funding_records=[{"timestamp": 0, "fundingRate": 0.0002, "nextFundingRate": 0.0003, "markPrice": 65000.0, "interval": "8h"}])
    result = ccxt_generic.fetch_funding_rate_history_range(exchange, "BTC/USDT:USDT", since_ms=0, until_ms=0)
    assert result == [
        {"timestamp_ms": 0, "funding_rate": 0.0002, "predicted_next_rate": 0.0003, "mark_price": 65000.0, "funding_interval_hours": 8}
    ]


def test_fetch_funding_rate_history_range_defaults_interval_when_missing():
    exchange = FakeExchange(funding_records=[mk_funding_record(0)])
    result = ccxt_generic.fetch_funding_rate_history_range(exchange, "BTC/USDT:USDT", since_ms=0, until_ms=0)
    assert result[0]["funding_interval_hours"] == ccxt_generic.DEFAULT_FUNDING_INTERVAL_HOURS


def test_fetch_funding_rate_history_range_stops_on_empty_page():
    exchange = FakeExchange(funding_records=[mk_funding_record(0)])
    result = ccxt_generic.fetch_funding_rate_history_range(exchange, "BTC/USDT:USDT", since_ms=0, until_ms=100 * HOUR_MS)
    assert [r["timestamp_ms"] for r in result] == [0]


def test_fetch_funding_rate_history_range_excludes_records_past_until_ms():
    records = [mk_funding_record(i * HOUR_MS) for i in range(5)]
    exchange = FakeExchange(funding_records=records)
    result = ccxt_generic.fetch_funding_rate_history_range(exchange, "BTC/USDT:USDT", since_ms=0, until_ms=2 * HOUR_MS, page_limit=10)
    assert [r["timestamp_ms"] for r in result] == [0, HOUR_MS, 2 * HOUR_MS]


# --- fetch_open_interest (latest snapshot) ---


def test_fetch_open_interest_shapes_snapshot():
    exchange = FakeExchange()
    exchange.oi_snapshot = {"timestamp": HOUR_MS, "openInterestAmount": 5000.0, "openInterestValue": 325_000_000.0}
    result = ccxt_generic.fetch_open_interest(exchange, "BTC/USDT:USDT")
    assert result == {"timestamp_ms": HOUR_MS, "oi_contracts": 5000.0, "oi_usd": 325_000_000.0}


def test_fetch_open_interest_oi_usd_none_when_venue_omits_it():
    # Bybit's linear markets never populate openInterestValue (parse_open_
    # interest's own source: value is inverse-contract-only there).
    exchange = FakeExchange()
    exchange.oi_snapshot = {"timestamp": HOUR_MS, "openInterestAmount": 5000.0, "openInterestValue": None}
    result = ccxt_generic.fetch_open_interest(exchange, "BTC/USDT:USDT")
    assert result["oi_usd"] is None


# --- fetch_open_interest_history_range (F0e P2, pagination) ---


def test_fetch_open_interest_history_range_pages_across_multiple_calls():
    records = [mk_oi_record(i * HOUR_MS) for i in range(10)]
    exchange = FakeExchange(oi_records=records)
    result = ccxt_generic.fetch_open_interest_history_range(exchange, "BTC/USDT:USDT", "1h", since_ms=0, until_ms=9 * HOUR_MS, page_limit=3)
    assert [r["timestamp_ms"] for r in result] == [i * HOUR_MS for i in range(10)]
    assert len(exchange.oi_calls) == 4


def test_fetch_open_interest_history_range_advances_cursor_by_timeframe_duration():
    records = [mk_oi_record(i * HOUR_MS) for i in range(5)]
    exchange = FakeExchange(oi_records=records, timeframe_seconds=3600)
    ccxt_generic.fetch_open_interest_history_range(exchange, "BTC/USDT:USDT", "1h", since_ms=0, until_ms=4 * HOUR_MS, page_limit=2)
    assert exchange.oi_calls[1]["since"] == 2 * HOUR_MS  # timeframe-bucketed, same as OHLCV (unlike funding history)


def test_fetch_open_interest_history_range_passes_timeframe_through():
    exchange = FakeExchange(oi_records=[mk_oi_record(0)])
    ccxt_generic.fetch_open_interest_history_range(exchange, "BTC/USDT:USDT", "5m", since_ms=0, until_ms=0)
    assert exchange.oi_calls[0]["timeframe"] == "5m"


def test_fetch_open_interest_history_range_shapes_records():
    exchange = FakeExchange(oi_records=[mk_oi_record(0, amount=5000.0, value=325_000_000.0)])
    result = ccxt_generic.fetch_open_interest_history_range(exchange, "BTC/USDT:USDT", "1h", since_ms=0, until_ms=0)
    assert result == [{"timestamp_ms": 0, "oi_contracts": 5000.0, "oi_usd": 325_000_000.0}]
