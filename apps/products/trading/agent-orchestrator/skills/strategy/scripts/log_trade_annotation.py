"""Manual CLI to log one real trade into trade_annotation
(docs/shadow-simulator-brief.md Option 2). The founder logging real
trades here is what unblocks everything downstream: shadow_pair pairing,
fidelity scoring, and any ML risk-envelope fitting all wait on this data
existing at all -- brief Section 5's cold start is explicit: "sebelum ada
>= ~50 pasangan shadow, SEMUA parameter pakai default rule-based."

Usage:
    python3 scripts/log_trade_annotation.py \\
        --tenant-email founder@example.com \\
        --venue binance --symbol "BTC/USDT:USDT" \\
        --ts 2026-07-03T14:00:00+00:00 --action short \\
        --leverage 10 --margin-mode isolated \\
        --entry-fill-price 60500.5 --exit-fill-price 59800.25 \\
        --exit-reason-real take_profit --dry-run

Drop --dry-run once the printed preview looks right -- it's the only
thing standing between a typo and a real INSERT.

Every field is optional except tenant/instrument/ts/action (the table's
own NOT NULL columns, unchanged since migration 0001) -- a real trade
logged before its fib/gann analysis context is fully written up is still
valid data, same as the brief's own point that a signal without a real
trade behind it stays valid too. No signal_id linkage yet (see migration
0005's docstring) -- this script logs one annotation row, it does not
pair it to a specific generated signal.

RLS note: trade_annotation is FORCE ROW LEVEL SECURITY'd (docs/prd.md
Section B.4) -- an INSERT is rejected by the WITH CHECK clause unless
app.tenant_id is set to the row's own tenant_id first in the same
session (SELECT set_config(...), never a bare SET with a bind parameter,
per docs/deployment-runbook.md's RLS gotchas). This script does that
before inserting; skipping it is what a raw `psql` INSERT would silently
get wrong.

Not pytest-covered end-to-end (needs a real DATABASE_URL and writes to a
real table, same as data_loader.py/ingest.py) -- the pure parsing/
validation pieces (parse_ts, build_row, build_parser) are unit tested,
and the actual INSERT + RLS enforcement was verified against a real
local Postgres 16 with every migration applied (0001-0005) and a
non-superuser role (RLS is a no-op for superusers, same caveat as every
other RLS verification this session) -- see docs/fib-gann-validation-
brief.md Section 19.

kinetiq_db/sqlalchemy are imported lazily, inside the functions that
actually touch the DB, not at module level: CI's `test` job deliberately
does not install packages/db (same reason run_validation.py defers its
data_loader import), so an eager import here would break collection for
this file's own pure-logic tests even though they never call the DB.
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../../../../packages/db/src"))


def parse_ts(value: str) -> datetime.datetime:
    ts = datetime.datetime.fromisoformat(value)
    if ts.tzinfo is None:
        raise SystemExit(f"--ts must include a UTC offset (e.g. ...+00:00): {value!r}")
    return ts


def build_row(args: argparse.Namespace) -> dict:
    """Pure -- builds every column EXCEPT tenant_id/instrument_id, which
    need a DB lookup and are added by the caller after this."""
    return {
        "ts": parse_ts(args.ts),
        "swing_ref": json.loads(args.swing_ref) if args.swing_ref else None,
        "fib_level": args.fib_level,
        "gann_angle": args.gann_angle,
        "action": args.action,
        "rationale_text": args.rationale_text,
        "leverage": args.leverage,
        "margin_mode": args.margin_mode,
        "entry_fill_price": args.entry_fill_price,
        "exit_fill_price": args.exit_fill_price,
        "fees_paid_usd": args.fees_paid_usd,
        "funding_paid_usd": args.funding_paid_usd,
        "exit_reason_real": args.exit_reason_real,
    }


def resolve_tenant_id(session, tenant_id: str | None, tenant_email: str | None):
    if tenant_id:
        return tenant_id
    from kinetiq_db.models import Tenant
    from sqlalchemy import select

    row = session.execute(select(Tenant.id).where(Tenant.email == tenant_email)).first()
    if row is None:
        raise SystemExit(f"no tenant found with email {tenant_email!r}")
    return row.id


def resolve_instrument_id(session, venue: str, symbol: str) -> int:
    from kinetiq_db.models import Instrument, Venue
    from sqlalchemy import select

    query = select(Instrument.id).join(Venue, Venue.id == Instrument.venue_id).where(Venue.name == venue, Instrument.symbol == symbol)
    row = session.execute(query).first()
    if row is None:
        raise SystemExit(f"no instrument found for venue={venue!r} symbol={symbol!r}")
    return row.id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--venue", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--ts", required=True, help="ISO 8601, must include a UTC offset")
    parser.add_argument("--action", required=True, help="e.g. long/short -- not DB-constrained, but that's the existing convention")

    tenant_group = parser.add_mutually_exclusive_group(required=True)
    tenant_group.add_argument("--tenant-id")
    tenant_group.add_argument("--tenant-email")

    parser.add_argument("--fib-level", type=float)
    parser.add_argument("--gann-angle")
    parser.add_argument("--rationale", dest="rationale_text")
    parser.add_argument("--swing-ref", help='JSON string, e.g. \'{"pivot_price": 60000, "pivot_index": 91}\'')

    parser.add_argument("--leverage", type=float)
    parser.add_argument("--margin-mode", choices=["cross", "isolated"])
    parser.add_argument("--entry-fill-price", type=float)
    parser.add_argument("--exit-fill-price", type=float)
    parser.add_argument("--fees-paid-usd", type=float)
    parser.add_argument("--funding-paid-usd", type=float)
    parser.add_argument("--exit-reason-real", choices=["stop_loss", "take_profit", "liquidated", "timeout", "manual_override"])

    parser.add_argument("--dry-run", action="store_true", help="print what would be inserted, touch nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    row = build_row(args)

    if args.dry_run:
        preview = {**row, "venue": args.venue, "symbol": args.symbol, "tenant_id": args.tenant_id, "tenant_email": args.tenant_email}
        print("DRY RUN -- would insert (tenant/instrument not resolved, no DB touched):")
        print(json.dumps(preview, indent=2, default=str))
        return 0

    from kinetiq_db.engine import normalize_db_url
    from kinetiq_db.models import TradeAnnotation
    from sqlalchemy import create_engine, func, insert, select
    from sqlalchemy.orm import Session

    engine = create_engine(normalize_db_url(os.environ["DATABASE_URL"]))
    with Session(engine) as session, session.begin():
        tenant_id = resolve_tenant_id(session, args.tenant_id, args.tenant_email)
        instrument_id = resolve_instrument_id(session, args.venue, args.symbol)
        # SELECT set_config(...), never a bare SET with a bind parameter --
        # docs/deployment-runbook.md's RLS gotchas explain why the latter
        # is a Postgres syntax error, not just bad style.
        session.execute(select(func.set_config("app.tenant_id", str(tenant_id), False)))
        new_id = session.execute(
            insert(TradeAnnotation).values(tenant_id=tenant_id, instrument_id=instrument_id, **row).returning(TradeAnnotation.id)
        ).scalar_one()

    print(f"inserted trade_annotation id={new_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
