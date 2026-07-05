"""F0e P7 (docs/sonnet5-implementation-roadmap.md): monthly durable dump of
the `signal` table. Unlike ohlcv/funding_rate/open_interest (all
re-backfillable from the exchange after the fact), `signal` is the ONLY
record of Shadow Tahap 1's genuine forward/out-of-sample signal
generation -- once a row is lost it can never be recreated. Neon's
point-in-time-recovery window is a first line of defense but bounded (7
days as of 2026-07-05, per the project's own history_retention_seconds);
this script is the second, independent line: a full snapshot committed
straight into the repo every month.

Deliberately committed to git rather than uploaded as a GitHub Actions
artifact -- this repo already learned that lesson the hard way (campaign
report run #2's artifact expired Oct 2026, see monthly-campaign.yml's own
header comment), so .github/workflows/monthly-signal-dump.yml follows the
exact same "commit into the repo" fix.

Reuses the same kinetiq_db models/connection pattern as data_loader.py/
ingest.py (create_engine(normalize_db_url(...))) -- read-only, no writes.
Not covered by this repo's pytest suite for the DB-touching fetch itself
(same "verified manually/via a real CI run against a real Neon branch"
discipline as ingest.py's own module docstring) -- but rows_to_records()
is a pure transform and IS unit-tested (test_dump_signal_table.py).
"""

import datetime
import json
import os
import sys
from decimal import Decimal

from kinetiq_db.engine import normalize_db_url
from kinetiq_db.models import Instrument, Signal, Venue
from sqlalchemy import create_engine, select


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    raise TypeError(f"not JSON-serializable: {type(value)!r}")


def rows_to_records(rows) -> list[dict]:
    """Pure transform -- one JSON-serializable dict per signal row, keyed
    by readable venue/symbol/timeframe rather than raw instrument_id, so
    the dump is self-contained and human-inspectable years later without
    needing to cross-reference the `instrument` table (which could itself
    change). Takes anything with these attributes (a SQLAlchemy Row in
    production, a plain object in tests) -- kept duck-typed rather than
    tied to a specific Row type so this stays trivially unit-testable."""
    return [
        {
            "id": row.id,
            "venue": row.venue_name,
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "ts": row.ts.isoformat(),
            "direction": row.direction,
            "entry_price": float(row.entry_price),
            "stop_loss": float(row.stop_loss),
            "take_profit_1": float(row.take_profit_1) if row.take_profit_1 is not None else None,
            "confidence": float(row.confidence),
            "factor_scores": row.factor_scores,
            "created_at": row.created_at.isoformat() if row.created_at is not None else None,
        }
        for row in rows
    ]


def fetch_all_signals(database_url: str) -> list[dict]:
    engine = create_engine(normalize_db_url(database_url))
    query = (
        select(
            Signal.id,
            Venue.name.label("venue_name"),
            Instrument.symbol,
            Signal.timeframe,
            Signal.ts,
            Signal.direction,
            Signal.entry_price,
            Signal.stop_loss,
            Signal.take_profit_1,
            Signal.confidence,
            Signal.factor_scores,
            Signal.created_at,
        )
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .join(Venue, Venue.id == Instrument.venue_id)
        .order_by(Signal.id.asc())
    )
    with engine.connect() as conn:
        rows = list(conn.execute(query))
    return rows_to_records(rows)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    output_path = argv[0]
    records = fetch_all_signals(os.environ["DATABASE_URL"])
    with open(output_path, "w") as f:
        json.dump(records, f, indent=2, default=_json_default)
        f.write("\n")
    print(f"dumped {len(records)} signal rows to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
