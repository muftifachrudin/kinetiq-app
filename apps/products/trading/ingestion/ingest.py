"""Entrypoint: fetch funding rate + OHLCV from one or more CEX venues (via
the connector in connectors/cex/ccxt_generic.py) and upsert into Neon.
Standalone script for now -- not yet wired into Inngest scheduling, which
doesn't exist in this repo yet (Section B.1/B.9). Run manually or via cron
until then.
"""

import argparse
import dataclasses
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "connectors", "cex"))

import ccxt_generic  # noqa: E402
import native_fallback  # noqa: E402
from kinetiq_db.engine import normalize_db_url  # noqa: E402
from kinetiq_db.models import DataSourceHealth, FundingRate, Instrument, Ohlcv, OpenInterest, Venue  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

# Fallback chain (docs/prd.md Section B.11): ccxt is always tried first on
# every run (so a recovered ccxt path is detected automatically), but once
# a venue+data_type has already failed this many times in a row (tracked in
# data_source_health, which existed before this and needed no schema
# change), a failure on *this* attempt also tries native_fallback.FALLBACKS
# before giving up -- escalate to the native REST path only once there's
# real evidence of a sustained problem, not on every transient blip.
FALLBACK_THRESHOLD = 3

# Adding a new venue: it must be supported by ccxt with fetch_funding_rate
# (or fetch_funding_rates, see ccxt_generic.py) + fetch_ohlcv. venue_type
# must match the `ck_venue_type` DB constraint ('cex' or 'dex'). API key env
# vars follow the "<VENUE>_API_KEY"/"<VENUE>_API_SECRET" pattern for venues
# that authenticate that way (CEX venues) -- use None/None for venues that
# don't (e.g. Hyperliquid uses walletAddress/privateKey instead, moot here
# since this script only calls public endpoints).
VENUES = {
    "binance": {
        "ccxt_id": "binanceusdm",
        "venue_type": "cex",
        "api_key_env": "BINANCE_API_KEY",
        "api_secret_env": "BINANCE_API_SECRET",
    },
    "bybit": {
        "ccxt_id": "bybit",
        "venue_type": "cex",
        "api_key_env": "BYBIT_API_KEY",
        "api_secret_env": "BYBIT_API_SECRET",
    },
    "hyperliquid": {
        "ccxt_id": "hyperliquid",
        "venue_type": "dex",
        "api_key_env": None,
        "api_secret_env": None,
    },
}


def get_session() -> Session:
    engine = create_engine(normalize_db_url(os.environ["DATABASE_URL"]))
    return sessionmaker(bind=engine)()


def upsert_venue(db: Session, venue_name: str, venue_type: str) -> Venue:
    venue = db.query(Venue).filter_by(name=venue_name).one_or_none()
    if venue is None:
        venue = Venue(name=venue_name, venue_type=venue_type)
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


def get_consecutive_failures(db: Session, venue: Venue, data_type: str) -> int:
    health = db.query(DataSourceHealth).filter_by(venue_id=venue.id, data_type=data_type).one_or_none()
    return health.consecutive_failures or 0 if health else 0


def get_fallback(venue_name: str, data_type: str, consecutive_failures: int):
    """Returns the native_fallback function to try after a ccxt failure, or
    None if this venue+data_type has no native fallback (e.g. hyperliquid,
    see native_fallback.py) or hasn't failed FALLBACK_THRESHOLD times in a
    row yet."""
    if consecutive_failures < FALLBACK_THRESHOLD:
        return None
    return native_fallback.FALLBACKS.get(venue_name, {}).get(data_type)


def _ts(timestamp_ms: int | None) -> datetime:
    if timestamp_ms is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def ingest_funding_rate(
    db: Session, exchange, instrument: Instrument, venue_symbol: str, fallback_fn=None
) -> str:
    """Returns "ccxt" or "native fallback" indicating which source supplied
    the data actually written, for logging -- fallback_fn is only called if
    the ccxt path raises, and only re-raises if fallback_fn does too (or is
    None, i.e. no fallback available/eligible for this call)."""
    try:
        data = ccxt_generic.fetch_funding_rate(exchange, venue_symbol)
        source = "ccxt"
    except Exception:
        if fallback_fn is None:
            raise
        data = fallback_fn(venue_symbol)
        source = "native fallback"

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
    return source


def ingest_open_interest(db: Session, exchange, instrument: Instrument, venue_symbol: str) -> str:
    """F0e P2 (docs/sonnet5-implementation-roadmap.md): closes the "open_
    interest is 0 rows" gap -- ccxt-only, no native_fallback path (unlike
    ingest_funding_rate/ingest_ohlcv): native_fallback.py has no OI
    implementation yet, there's no fallback to try. Always returns "ccxt"
    (kept as a return value anyway for the same logging contract as the
    other two ingest_* functions, and so a future fallback addition here
    wouldn't need to change every caller's expectations)."""
    data = ccxt_generic.fetch_open_interest(exchange, venue_symbol)
    db.merge(
        OpenInterest(
            instrument_id=instrument.id,
            ts=_ts(data["timestamp_ms"]),
            oi_contracts=data["oi_contracts"],
            oi_usd=data["oi_usd"],
        )
    )
    db.commit()
    return "ccxt"


def ingest_ohlcv(
    db: Session, exchange, instrument: Instrument, venue_symbol: str, timeframe: str, limit: int, fallback_fn=None
) -> str:
    """Returns "ccxt" or "native fallback", same contract as ingest_funding_rate."""
    try:
        candles = ccxt_generic.fetch_ohlcv(exchange, venue_symbol, timeframe, limit)
        source = "ccxt"
    except Exception:
        if fallback_fn is None:
            raise
        candles = fallback_fn(venue_symbol, timeframe, limit)
        source = "native fallback"

    for candle in candles:
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
    return source


def earliest_ohlcv_ts(db: Session, instrument: Instrument, timeframe: str) -> datetime | None:
    row = (
        db.query(Ohlcv.ts)
        .filter_by(instrument_id=instrument.id, timeframe=timeframe)
        .order_by(Ohlcv.ts.asc())
        .first()
    )
    return row.ts if row else None


def earliest_funding_rate_ts(db: Session, instrument: Instrument) -> datetime | None:
    row = db.query(FundingRate.ts).filter_by(instrument_id=instrument.id).order_by(FundingRate.ts.asc()).first()
    return row.ts if row else None


def earliest_open_interest_ts(db: Session, instrument: Instrument) -> datetime | None:
    row = db.query(OpenInterest.ts).filter_by(instrument_id=instrument.id).order_by(OpenInterest.ts.asc()).first()
    return row.ts if row else None


def needs_backfill(existing_earliest: datetime | None, requested_since: datetime, tolerance: timedelta = timedelta(0)) -> bool:
    """Pure decision so a worker restart is cheap: once ohlcv already has a
    candle at or before requested_since (within `tolerance`) for this
    (instrument, timeframe), the range is considered covered and
    backfill_if_needed() skips re-paging it entirely.

    `tolerance` matters because candles land on timeframe-aligned
    boundaries, not on the arbitrary wall-clock instant requested_since
    happens to be -- a real bug caught via manual end-to-end testing
    against a local Postgres + real Hyperliquid data: requesting
    "5 days ago" at 07:14:27 backfills candles starting at the next 1h
    boundary (08:00:00), which is LATER than 07:14:27 even though nothing
    was actually missed (there's no 1h candle between 07:14 and 08:00 to
    have fetched anyway). Without a tolerance, every re-run re-triggered a
    full backfill instead of skipping -- the exact "cheap to re-run"
    property this function exists to guarantee. backfill_if_needed() passes
    one timeframe's duration as the tolerance.

    Still does NOT detect gaps in the middle of an otherwise-covered range
    (e.g. a partial backfill interrupted mid-run, then resumed with an
    earlier --backfill-since than the interrupted attempt used) --
    documented simplification, not a hidden one: a resumed backfill with the
    SAME or a LATER --backfill-since than a prior complete run is safe and
    cheap; an earlier one after a prior run was itself incomplete is not
    guaranteed gap-free."""
    if existing_earliest is None:
        return True
    return existing_earliest > requested_since + tolerance


def backfill_ohlcv(
    db: Session, exchange, instrument: Instrument, venue_symbol: str, timeframe: str, since_ms: int, until_ms: int | None = None
) -> int:
    """Pages the full [since_ms, until_ms] range via ccxt_generic.fetch_ohlcv_range
    and merges every candle -- same idempotent db.merge()-per-row + single
    commit pattern as ingest_ohlcv(), just fed a much longer candle list.
    CCXT-only, no native_fallback path: a deep historical page-through isn't
    something native_fallback.py supports today (see its own module docstring
    -- it only ever fetches the latest N), and this is a one-time/occasional
    operation rather than something that needs the same failure resilience as
    the live polling path. Returns the number of candles written, for the
    caller to log."""
    candles = ccxt_generic.fetch_ohlcv_range(exchange, venue_symbol, timeframe, since_ms, until_ms)
    for candle in candles:
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
    return len(candles)


def backfill_if_needed(
    db: Session, exchange, instrument: Instrument, venue_symbol: str, timeframe: str, since: datetime
) -> int | None:
    """Returns the candle count written, or None if skipped because the
    range's already covered (see needs_backfill()). tolerance is one
    timeframe's duration -- candles land on timeframe-aligned boundaries,
    not on `since`'s exact wall-clock instant (see needs_backfill()'s
    docstring)."""
    tolerance = timedelta(seconds=exchange.parse_timeframe(timeframe))
    if not needs_backfill(earliest_ohlcv_ts(db, instrument, timeframe), since, tolerance):
        return None
    since_ms = int(since.timestamp() * 1000)
    return backfill_ohlcv(db, exchange, instrument, venue_symbol, timeframe, since_ms)


def backfill_funding_rate(
    db: Session, exchange, instrument: Instrument, venue_symbol: str, since_ms: int, until_ms: int | None = None
) -> int:
    """F0e P2: pages ccxt_generic.fetch_funding_rate_history_range() and
    merges every record -- same idempotent db.merge()-per-row + single
    commit pattern as backfill_ohlcv(). CCXT-only, same reasoning as
    ingest_open_interest(): no native_fallback path exists for history
    endpoints, and this is a one-time/occasional operation, not the live
    polling path's resilience requirement."""
    records = ccxt_generic.fetch_funding_rate_history_range(exchange, venue_symbol, since_ms, until_ms)
    for record in records:
        db.merge(
            FundingRate(
                instrument_id=instrument.id,
                ts=_ts(record["timestamp_ms"]),
                funding_rate=record["funding_rate"],
                predicted_next_rate=record["predicted_next_rate"],
                funding_interval_hours=record["funding_interval_hours"],
                mark_price=record["mark_price"],
            )
        )
    db.commit()
    return len(records)


def backfill_open_interest(
    db: Session, exchange, instrument: Instrument, venue_symbol: str, timeframe: str, since_ms: int, until_ms: int | None = None
) -> int:
    """F0e P2: pages ccxt_generic.fetch_open_interest_history_range() and
    merges every record -- same pattern as backfill_funding_rate()/
    backfill_ohlcv()."""
    records = ccxt_generic.fetch_open_interest_history_range(exchange, venue_symbol, timeframe, since_ms, until_ms)
    for record in records:
        db.merge(
            OpenInterest(
                instrument_id=instrument.id,
                ts=_ts(record["timestamp_ms"]),
                oi_contracts=record["oi_contracts"],
                oi_usd=record["oi_usd"],
            )
        )
    db.commit()
    return len(records)


def backfill_funding_rate_if_needed(db: Session, exchange, instrument: Instrument, venue_symbol: str, since: datetime) -> int | None:
    """Same skip-if-covered contract as backfill_if_needed(), tolerance is
    one funding interval's duration (funding_rate has no fixed per-venue
    timeframe to parse -- DEFAULT_FUNDING_INTERVAL_HOURS is ccxt_generic.py's
    own "8h unless the venue says otherwise" fallback, reused here rather
    than duplicated)."""
    tolerance = timedelta(hours=ccxt_generic.DEFAULT_FUNDING_INTERVAL_HOURS)
    if not needs_backfill(earliest_funding_rate_ts(db, instrument), since, tolerance):
        return None
    since_ms = int(since.timestamp() * 1000)
    return backfill_funding_rate(db, exchange, instrument, venue_symbol, since_ms)


def backfill_open_interest_if_needed(
    db: Session, exchange, instrument: Instrument, venue_symbol: str, timeframe: str, since: datetime
) -> int | None:
    """Same skip-if-covered contract as backfill_if_needed(), tolerance is
    one `timeframe` bucket's duration -- OI history IS timeframe-bucketed
    (unlike funding rate history), same reasoning as backfill_if_needed()'s
    own tolerance."""
    tolerance = timedelta(seconds=exchange.parse_timeframe(timeframe))
    if not needs_backfill(earliest_open_interest_ts(db, instrument), since, tolerance):
        return None
    since_ms = int(since.timestamp() * 1000)
    return backfill_open_interest(db, exchange, instrument, venue_symbol, timeframe, since_ms)


@dataclasses.dataclass
class VenueContext:
    venue_name: str
    venue: Venue
    exchange: object
    instruments: list[tuple[str, Instrument]]  # (venue_symbol, Instrument)


def setup_venues(db: Session, venue_names: list[str], symbols: list[str]) -> list[VenueContext]:
    """One-time-per-process setup: creates each exchange + load_markets()
    (a real network round-trip) and upserts venue/instrument rows. Split out
    from run() so worker.py's poll loop can build this ONCE and reuse it
    across many cycles instead of re-hitting load_markets() every single
    poll -- that's the difference between "efficient" polling and
    accidentally re-paying an expensive setup cost every few minutes
    forever."""
    contexts = []
    for venue_name in venue_names:
        cfg = VENUES[venue_name]
        exchange = ccxt_generic.make_exchange(cfg["ccxt_id"], cfg["api_key_env"], cfg["api_secret_env"])
        exchange.load_markets()
        venue = upsert_venue(db, venue_name, cfg["venue_type"])
        db.commit()

        instruments = []
        for venue_symbol in symbols:
            market = exchange.market(venue_symbol)
            instrument = upsert_instrument(db, venue, market)
            db.commit()
            instruments.append((venue_symbol, instrument))

        contexts.append(VenueContext(venue_name=venue_name, venue=venue, exchange=exchange, instruments=instruments))
    return contexts


def poll_once(db: Session, contexts: list[VenueContext], timeframe: str, limit: int) -> None:
    """The latest-N live path: one funding_rate + one ohlcv fetch per
    instrument, same fallback/health-tracking behavior run() always had."""
    for ctx in contexts:
        for venue_symbol, instrument in ctx.instruments:
            fr_failures = get_consecutive_failures(db, ctx.venue, "funding_rate")
            fr_fallback = get_fallback(ctx.venue_name, "funding_rate", fr_failures)
            try:
                source = ingest_funding_rate(db, ctx.exchange, instrument, venue_symbol, fr_fallback)
                record_health(db, ctx.venue, "funding_rate", success=True)
                print(f"[{ctx.venue_name}:{venue_symbol}] funding_rate OK ({source})")
            except Exception as exc:
                db.rollback()
                record_health(db, ctx.venue, "funding_rate", success=False)
                print(f"[{ctx.venue_name}:{venue_symbol}] funding_rate FAILED: {exc}")

            ohlcv_failures = get_consecutive_failures(db, ctx.venue, "ohlcv")
            ohlcv_fallback = get_fallback(ctx.venue_name, "ohlcv", ohlcv_failures)
            try:
                source = ingest_ohlcv(db, ctx.exchange, instrument, venue_symbol, timeframe, limit, ohlcv_fallback)
                record_health(db, ctx.venue, "ohlcv", success=True)
                print(f"[{ctx.venue_name}:{venue_symbol}] ohlcv OK ({source})")
            except Exception as exc:
                db.rollback()
                record_health(db, ctx.venue, "ohlcv", success=False)
                print(f"[{ctx.venue_name}:{venue_symbol}] ohlcv FAILED: {exc}")

            # F0e P2 (docs/sonnet5-implementation-roadmap.md): open_interest
            # was 0 rows before this -- no native fallback exists yet (see
            # ingest_open_interest()'s own docstring), so a failure here just
            # gets tracked/logged like the other two, no fallback attempt.
            try:
                source = ingest_open_interest(db, ctx.exchange, instrument, venue_symbol)
                record_health(db, ctx.venue, "open_interest", success=True)
                print(f"[{ctx.venue_name}:{venue_symbol}] open_interest OK ({source})")
            except Exception as exc:
                db.rollback()
                record_health(db, ctx.venue, "open_interest", success=False)
                print(f"[{ctx.venue_name}:{venue_symbol}] open_interest FAILED: {exc}")


def backfill_run(db: Session, contexts: list[VenueContext], timeframe: str, since: datetime) -> None:
    """CCXT-only (see backfill_ohlcv()) -- no fallback/health-tracking dance,
    just page each instrument's history and log what happened. Meant to run
    once (or occasionally, cheaply thanks to needs_backfill()'s skip), not
    on every poll cycle."""
    for ctx in contexts:
        for venue_symbol, instrument in ctx.instruments:
            try:
                written = backfill_if_needed(db, ctx.exchange, instrument, venue_symbol, timeframe, since)
                if written is None:
                    print(f"[{ctx.venue_name}:{venue_symbol}] backfill SKIPPED (already covers {since.isoformat()})")
                else:
                    print(f"[{ctx.venue_name}:{venue_symbol}] backfill OK ({written} candles since {since.isoformat()})")
            except Exception as exc:
                db.rollback()
                print(f"[{ctx.venue_name}:{venue_symbol}] backfill FAILED: {exc}")


def backfill_run_funding_rate(db: Session, contexts: list[VenueContext], since: datetime) -> None:
    """F0e P2: same shape as backfill_run(), for funding rate HISTORY (the
    live-poll path in poll_once() only ever wrote the current rate)."""
    for ctx in contexts:
        for venue_symbol, instrument in ctx.instruments:
            try:
                written = backfill_funding_rate_if_needed(db, ctx.exchange, instrument, venue_symbol, since)
                if written is None:
                    print(f"[{ctx.venue_name}:{venue_symbol}] funding_rate backfill SKIPPED (already covers {since.isoformat()})")
                else:
                    print(f"[{ctx.venue_name}:{venue_symbol}] funding_rate backfill OK ({written} records since {since.isoformat()})")
            except Exception as exc:
                db.rollback()
                print(f"[{ctx.venue_name}:{venue_symbol}] funding_rate backfill FAILED: {exc}")


def backfill_run_open_interest(db: Session, contexts: list[VenueContext], timeframe: str, since: datetime) -> None:
    """F0e P2: same shape as backfill_run(), for open interest history."""
    for ctx in contexts:
        for venue_symbol, instrument in ctx.instruments:
            try:
                written = backfill_open_interest_if_needed(db, ctx.exchange, instrument, venue_symbol, timeframe, since)
                if written is None:
                    print(f"[{ctx.venue_name}:{venue_symbol}] open_interest backfill SKIPPED (already covers {since.isoformat()})")
                else:
                    print(f"[{ctx.venue_name}:{venue_symbol}] open_interest backfill OK ({written} records since {since.isoformat()})")
            except Exception as exc:
                db.rollback()
                print(f"[{ctx.venue_name}:{venue_symbol}] open_interest backfill FAILED: {exc}")


def run(venue_names: list[str], symbols: list[str], timeframe: str, limit: int) -> None:
    db = get_session()
    contexts = setup_venues(db, venue_names, symbols)
    poll_once(db, contexts, timeframe, limit)
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venues", nargs="+", choices=list(VENUES), default=["binance", "bybit"])
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTC/USDT:USDT", "ETH/USDT:USDT"],
        help=(
            "Same symbol list is used for every --venues entry in this run "
            "-- venues with a different quote currency (e.g. hyperliquid's "
            "USDC-quoted perps, 'BTC/USDC:USDC') must be run as a separate "
            "invocation, not mixed with binance/bybit's USDT-quoted default."
        ),
    )
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--backfill-since-days",
        type=int,
        default=None,
        help=(
            "If given, page through and merge every candle from N days ago to now "
            "(see backfill_ohlcv()) BEFORE the normal latest-N poll below -- skipped "
            "automatically per (venue, symbol) if ohlcv already covers that range "
            "(needs_backfill()), so re-running this is cheap."
        ),
    )
    args = parser.parse_args()

    db = get_session()
    contexts = setup_venues(db, args.venues, args.symbols)
    if args.backfill_since_days is not None:
        since = datetime.now(timezone.utc) - timedelta(days=args.backfill_since_days)
        backfill_run(db, contexts, args.timeframe, since)
    poll_once(db, contexts, args.timeframe, args.limit)
    db.close()
