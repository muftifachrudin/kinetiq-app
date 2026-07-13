"""Long-running worker: backfills OHLCV history once at startup (skipped
automatically per (venue, symbol) if already covered, see
ingest.needs_backfill), then polls forever for new candles aligned to each
timeframe's own close boundary -- the continuous alternative to ingest.py's
one-shot CLI.

Built directly in response to the founder's question (3 Juli 2026) on how
to backfill deeper OHLCV history efficiently while also keeping it current
going forward: production had been stuck at ~100 hourly candles because
nothing was ever scheduled to run ingest.py again after the first manual
invocation (apps/products/trading/ingestion/ingest.py's own docstring
already said as much -- "run manually or via cron until [Inngest exists]").
Rather than a CoinGlass Hobbyist subscription (its likely minimum interval
is 4h, and even generously reading its pricing table it tops out around 180
days of 1h data) OHLCV here is and stays CCXT/exchange-sourced -- Binance's
public klines endpoint already gives full history for free, no paid plan
needed at all, so the actual gap was capability (ingest.py couldn't page
through history) and scheduling (nothing kept running it), not a data
vendor limitation.

Deployed as ITS OWN Coolify application (see Dockerfile in this directory,
which replaced railway.ingestion-worker.toml 1:1 when compute moved off
Railway) -- ingest.py itself stays a plain library module + one-shot CLI
unchanged in its own right, this just orchestrates it on a loop. Founder
chose this over a GitHub Actions cron or running it manually/locally,
explicitly for true always-on polling rather than a delayed/periodic catch-
up.

Backfill runs synchronously before the poll loop starts (not on a separate
thread) -- deliberately, not a shortcut: ccxt's enableRateLimit already
paces every request about as fast as each exchange allows, so paging a
year of hourly candles across a couple of symbols is a matter of seconds
to low minutes even for a from-scratch backfill, not long enough to justify
the complexity/risk of a second thread sharing (or duplicating) the same
DB session and exchange objects. If a deployment ever needs a genuinely
deep multi-year backfill across many symbols, this assumption should be
revisited -- documented here rather than silently assumed forever.
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "connectors", "cex"))

import ccxt  # noqa: E402
import ingest  # noqa: E402
import signal_loop  # noqa: E402

_shutdown_requested = False


def _handle_shutdown(signum, frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True


def seconds_until_next_close(timeframe: str, now: datetime, buffer_seconds: int = 10) -> float:
    """Seconds to sleep so the worker wakes up just after the NEXT candle of
    this timeframe closes -- e.g. for "1h" at 14:23:00 UTC, wakes at
    15:00:10 (the buffer is a practical cushion for the exchange to finalize/
    publish the just-closed candle, not a guarantee it always has by then).
    Pure function of (timeframe, now) -- no real sleeping/clock dependency,
    fully unit-testable. Reuses ccxt.Exchange.parse_timeframe (a plain
    string->seconds parser, callable without an exchange instance) rather
    than reimplementing timeframe parsing."""
    timeframe_seconds = ccxt.Exchange.parse_timeframe(timeframe)
    epoch = now.timestamp()
    next_close = (epoch // timeframe_seconds + 1) * timeframe_seconds
    return (next_close - epoch) + buffer_seconds


def run_forever(
    venue_names: list[str],
    symbols: list[str],
    timeframe: str,
    poll_limit: int,
    backfill_since_days: int | None,
    should_stop=lambda: _shutdown_requested,
    sleep_fn=time.sleep,
    now_fn=lambda: datetime.now(timezone.utc),
    get_session_fn=ingest.get_session,
    setup_venues_fn=ingest.setup_venues,
    backfill_run_fn=ingest.backfill_run,
    poll_once_fn=ingest.poll_once,
    generate_signals=True,
    generate_signals_fn=signal_loop.run_signal_loop_once,
    backfill_15m_since_days: int | None = None,
    backfill_funding_since_days: int | None = None,
    backfill_oi_since_days: int | None = None,
    oi_backfill_timeframe: str = "1h",
    backfill_run_15m_fn=ingest.backfill_run,
    backfill_run_funding_fn=ingest.backfill_run_funding_rate,
    backfill_run_oi_fn=ingest.backfill_run_open_interest,
) -> None:
    """The *_fn params default to the real ingest.py functions -- tests
    inject fakes instead, so this function's own sequencing/looping logic
    (backfill once, then poll-sleep-poll-sleep until should_stop()) is
    exercised without touching a real DB or network.

    generate_signals_fn (F0e P3, docs/sonnet5-implementation-roadmap.md):
    runs right after poll_once_fn each cycle, same freshly-polled candles
    the OHLCV path just wrote -- Shadow Tahap 1's signal-collection loop,
    same process/service as the OHLCV poll rather than a new one (see
    signal_loop.py's own module docstring). Only exercised for `timeframe
    == "1h"` -- signal_runner.py/fib_gann_timing.py's HTF resampling (4h/1d)
    and ATR period assume a 1h entry timeframe throughout this codebase, so
    running this against a different --timeframe would be silently
    meaningless rather than genuinely supported. generate_signals=False
    (mirrors --no-backfill) is an escape hatch, not expected to be used in
    production.

    backfill_15m_since_days/backfill_funding_since_days/backfill_oi_since_days
    (F0e P1+P2): three SEPARATE one-time startup backfills, each opt-in
    (None = skip, matching --no-backfill's existing "None means don't run
    this step" convention) rather than defaulting to on -- unlike the main
    OHLCV backfill above (already proven safe/idempotent/cheap-to-skip in
    production), these are brand-new data paths the roadmap explicitly asks
    to roll out staged/verified one at a time (real HTTP-SQL count+coverage
    check after each), not silently enabled via a new default the moment
    this ships. Each is cheap to re-run on every restart once enabled,
    exactly like the main backfill (same needs_backfill()-based skip).
    """
    db = get_session_fn()
    contexts = setup_venues_fn(db, venue_names, symbols)

    if backfill_since_days is not None:
        since = now_fn() - timedelta(days=backfill_since_days)
        print(f"backfill starting: {backfill_since_days} days back ({since.isoformat()})")
        backfill_run_fn(db, contexts, timeframe, since)
        print("backfill done -- entering live poll loop")

    if backfill_15m_since_days is not None:
        since = now_fn() - timedelta(days=backfill_15m_since_days)
        print(f"15m backfill starting: {backfill_15m_since_days} days back ({since.isoformat()})")
        backfill_run_15m_fn(db, contexts, "15m", since)
        print("15m backfill done")

    if backfill_funding_since_days is not None:
        since = now_fn() - timedelta(days=backfill_funding_since_days)
        print(f"funding_rate backfill starting: {backfill_funding_since_days} days back ({since.isoformat()})")
        backfill_run_funding_fn(db, contexts, since)
        print("funding_rate backfill done")

    if backfill_oi_since_days is not None:
        since = now_fn() - timedelta(days=backfill_oi_since_days)
        print(f"open_interest backfill starting: {backfill_oi_since_days} days back ({since.isoformat()})")
        backfill_run_oi_fn(db, contexts, oi_backfill_timeframe, since)
        print("open_interest backfill done")

    while not should_stop():
        poll_once_fn(db, contexts, timeframe, poll_limit)
        if generate_signals and timeframe == "1h":
            generate_signals_fn(db, contexts, timeframe)
        sleep_seconds = seconds_until_next_close(timeframe, now_fn())
        print(f"sleeping {sleep_seconds:.0f}s until next {timeframe} close")
        sleep_fn(sleep_seconds)

    db.close()
    print("shutdown requested -- exited cleanly")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_shutdown)  # Railway sends SIGTERM on redeploy/stop
    signal.signal(signal.SIGINT, _handle_shutdown)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venues", nargs="+", choices=list(ingest.VENUES), default=["binance", "bybit"])
    parser.add_argument("--symbols", nargs="+", default=["BTC/USDT:USDT", "ETH/USDT:USDT"])
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument(
        "--poll-limit",
        type=int,
        default=5,
        help="candles re-fetched each cycle -- a few more than 1 covers a missed/late poll without re-paging real history",
    )
    parser.add_argument(
        "--backfill-since-days",
        type=int,
        default=1100,
        help=(
            "deep pull once at startup (and again on every restart, cheaply skipped once covered -- see "
            "ingest.needs_backfill). F0e P1: 1100 days (~3 years, back to ~2023-07) covers a full bull regime, "
            "not just the last year's dominant-bear/range data -- was 365. Pass 0 or a negative number's not "
            "valid; omit via --no-backfill instead"
        ),
    )
    parser.add_argument("--no-backfill", action="store_true", help="skip the startup backfill entirely, just poll")
    parser.add_argument(
        "--no-signals", action="store_true", help="skip Shadow Tahap 1 signal generation/persistence, just poll OHLCV/funding (see signal_loop.py)"
    )
    parser.add_argument(
        "--backfill-15m-since-days",
        type=int,
        default=None,
        help="F0e P1: one-time 15m OHLCV backfill (same lookback period as --backfill-since-days) -- opt-in, omitted by default (see run_forever()'s own docstring on why these new backfills default off)",
    )
    parser.add_argument(
        "--backfill-funding-since-days",
        type=int,
        default=None,
        help="F0e P2: one-time funding rate HISTORY backfill (fetchFundingRateHistory) -- opt-in, omitted by default",
    )
    parser.add_argument(
        "--backfill-oi-since-days",
        type=int,
        default=None,
        help="F0e P2: one-time open interest HISTORY backfill (fetchOpenInterestHistory) -- opt-in, omitted by default",
    )
    parser.add_argument("--oi-backfill-timeframe", default="1h", help="bucket size for the open_interest history backfill (F0e P2)")
    args = parser.parse_args()

    run_forever(
        args.venues,
        args.symbols,
        args.timeframe,
        args.poll_limit,
        None if args.no_backfill else args.backfill_since_days,
        generate_signals=not args.no_signals,
        backfill_15m_since_days=args.backfill_15m_since_days,
        backfill_funding_since_days=args.backfill_funding_since_days,
        backfill_oi_since_days=args.backfill_oi_since_days,
        oi_backfill_timeframe=args.oi_backfill_timeframe,
    )
