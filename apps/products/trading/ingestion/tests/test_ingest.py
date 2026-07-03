"""Only pure/logic-only functions are covered here -- everything else in
ingest.py touches a real DB Session or a real ccxt exchange and is (like
the rest of this module, per its own docstring) verified manually against
real Binance/Hyperliquid + a real Postgres, not via pytest. This matches
ingest.py's existing testing discipline rather than inventing DB/network
mocking machinery for a script nobody runs from CI anyway."""

import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "connectors", "cex"))
import ingest  # noqa: E402

UTC = datetime.timezone.utc


def test_needs_backfill_true_when_no_existing_data():
    assert ingest.needs_backfill(None, datetime.datetime(2024, 1, 1, tzinfo=UTC)) is True


def test_needs_backfill_true_when_existing_data_starts_later_than_requested():
    existing = datetime.datetime(2024, 6, 1, tzinfo=UTC)
    requested = datetime.datetime(2024, 1, 1, tzinfo=UTC)  # asking for MORE history than we have
    assert ingest.needs_backfill(existing, requested) is True


def test_needs_backfill_false_when_existing_data_already_covers_requested_range():
    existing = datetime.datetime(2024, 1, 1, tzinfo=UTC)
    requested = datetime.datetime(2024, 6, 1, tzinfo=UTC)  # we already have MORE history than requested
    assert ingest.needs_backfill(existing, requested) is False


def test_needs_backfill_false_when_existing_data_starts_exactly_at_requested():
    ts = datetime.datetime(2024, 1, 1, tzinfo=UTC)
    assert ingest.needs_backfill(ts, ts) is False


def test_needs_backfill_false_within_tolerance_of_next_boundary_candle():
    # real bug caught via manual end-to-end testing: requesting "since 07:14"
    # only ever produces a candle at the NEXT 1h boundary (08:00) -- that's
    # not a gap, so a tolerance of one timeframe's duration must still skip.
    existing = datetime.datetime(2024, 1, 1, 8, 0, 0, tzinfo=UTC)
    requested = datetime.datetime(2024, 1, 1, 7, 14, 27, tzinfo=UTC)
    assert ingest.needs_backfill(existing, requested, tolerance=datetime.timedelta(hours=1)) is False


def test_needs_backfill_true_when_gap_exceeds_tolerance():
    existing = datetime.datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    requested = datetime.datetime(2024, 1, 1, 7, 14, 27, tzinfo=UTC)  # gap is ~2h45m, bigger than a 1h tolerance
    assert ingest.needs_backfill(existing, requested, tolerance=datetime.timedelta(hours=1)) is True
