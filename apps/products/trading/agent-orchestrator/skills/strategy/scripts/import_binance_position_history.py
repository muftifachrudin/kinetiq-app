"""Bulk-import Binance Futures Position History (+ Trade History for fee
aggregation) into trade_annotation -- docs/shadow-simulator-brief.md
Option 2, the founder's own real trade history instead of one-at-a-time
manual entry via log_trade_annotation.py.

Usage:
    python3 scripts/import_binance_position_history.py \\
        --position-history PositionHistory.csv \\
        --trade-history TradeHistory.csv \\
        --tz-offset-hours 7 \\
        --dry-run

Source files are Binance's own CSV exports. Timestamps in these exports
are LOCAL time per the export filename (this founder's files say
"UTC7", i.e. UTC+7/WIB), NOT UTC -- parsed with an explicit
--tz-offset-hours so Postgres TIMESTAMPTZ stores them correctly
regardless (TIMESTAMPTZ normalizes any tz-aware input internally, this
just has to be the RIGHT offset going in).

What's reliably derivable from these exports, mapped 1:1:
  venue=binance, Symbol -> Instrument (auto-provisioned if missing, same
    idempotent upsert pattern as apps/products/trading/ingestion/
    ingest.py's upsert_instrument() -- most of these ~50 symbols,
    including Binance's tokenized-stock perpetuals like AAPLUSDT/
    MSFTUSDT/XAUUSDT, have never been ingested before)
  Opened -> ts, Position Side -> action, Entry Price -> entry_fill_price,
  Avg. Close Price -> exit_fill_price, Margin Mode -> margin_mode
  fees_paid_usd -- summed from Trade History fills matching (symbol, ts
    inside [Opened, Closed]) -- Position History alone doesn't carry fees

What's explicitly LEFT NULL, not guessed:
  leverage -- not present in any Binance CSV export at all
  exit_reason_real -- this founder's Order History export only ever has
    Type in {MARKET, LIMIT} (checked directly against the real file, not
    assumed) -- no STOP_MARKET/TAKE_PROFIT_MARKET/liquidation marker to
    infer stop_loss/take_profit/liquidated from. The founder separately
    noted some trades were manual overrides of a bot signal with very
    large returns -- that's real signal, but inferring WHICH specific
    rows from PnL alone would be guessing, not deriving; left for the
    founder to flag directly if wanted (e.g. a follow-up UPDATE).
  funding_paid_usd -- Binance's separate Income History export (not
    provided) is the actual source for this, not these files.
  rationale_text -- set to a fixed bulk-import provenance note (which
    CSV row, closing PnL) so these rows are identifiable later as bulk
    imports vs manually logged ones, not left blank.

Only "Closed" status positions are imported -- an open position has no
exit_fill_price yet, not annotatable as a completed trade (this
founder's export happened to be 100% Closed rows, checked directly, but
this isn't assumed for a different export).

Kinetiq is single-operator (migration 0009 dropped tenant_id/RLS from
trade_annotation along with the rest of the platform-core multi-tenant
layer) -- generated/executed SQL here is a plain INSERT, no set_config
session step needed anymore.

Not pytest-covered end-to-end (needs a real DATABASE_URL and writes to a
real table) -- CSV parsing/mapping/fee-aggregation are pure functions,
unit tested; the bulk INSERT reuses the exact pattern
log_trade_annotation.py already verified against real Postgres. See
docs/fib-gann-validation-brief.md Section 20 for the verification trail.
"""

import argparse
import csv
import dataclasses
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../../../../packages/db/src"))

_FEE_SUFFIX_RE = re.compile(r"[A-Za-z]+$")


def parse_local_ts(value: str, tz_offset_hours: float) -> datetime.datetime:
    naive = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return naive.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=tz_offset_hours)))


def to_instrument_symbol(binance_symbol: str) -> str:
    """"BTCUSDT" -> "BTC/USDT:USDT", matching ingest.py's ccxt-unified
    convention (Instrument.symbol == Instrument.venue_symbol for every
    row that module provisions). Only handles USDT-margined symbols --
    every row in a Binance Futures USDT-M export is one, and a symbol
    that isn't would indicate a different export type entirely, worth
    failing loudly on rather than silently mis-mapping."""
    if not binance_symbol.endswith("USDT"):
        raise ValueError(f"expected a USDT-margined symbol, got {binance_symbol!r}")
    base = binance_symbol[:-4]
    return f"{base}/USDT:USDT"


@dataclasses.dataclass(frozen=True)
class ParsedPosition:
    row_number: int  # 1-indexed position within the CSV, for traceability in rationale_text
    symbol: str  # Binance raw symbol, e.g. "BTCUSDT"
    margin_mode: str  # "cross" / "isolated"
    action: str  # "long" / "short"
    entry_price: float
    exit_price: float
    opened_ts: datetime.datetime
    closed_ts: datetime.datetime
    closing_pnl: float


def parse_position_history(path: str, tz_offset_hours: float) -> list[ParsedPosition]:
    positions = []
    with open(path, encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=1):
            if row["Status"] != "Closed":
                continue
            positions.append(
                ParsedPosition(
                    row_number=i,
                    symbol=row["Symbol"],
                    margin_mode=row["Margin Mode"].lower(),
                    action=row["Position Side"].lower(),
                    entry_price=float(row["Entry Price"]),
                    exit_price=float(row["Avg. Close Price"]),
                    opened_ts=parse_local_ts(row["Opened"], tz_offset_hours),
                    closed_ts=parse_local_ts(row["Closed"], tz_offset_hours),
                    closing_pnl=float(row["Closing PNL"]),
                )
            )
    return positions


@dataclasses.dataclass(frozen=True)
class TradeFill:
    symbol: str
    ts: datetime.datetime
    fee_usd: float


def parse_trade_history(path: str, tz_offset_hours: float) -> list[TradeFill]:
    fills = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            fee_str = row.get("Fee", "")
            fee_usd = float(_FEE_SUFFIX_RE.sub("", fee_str)) if fee_str else 0.0
            fills.append(TradeFill(symbol=row["Symbol"], ts=parse_local_ts(row["Time"], tz_offset_hours), fee_usd=fee_usd))
    return fills


def sum_fees_for_position(fills: list[TradeFill], position: ParsedPosition) -> float:
    return sum(fill.fee_usd for fill in fills if fill.symbol == position.symbol and position.opened_ts <= fill.ts <= position.closed_ts)


def build_row(position: ParsedPosition, fees_paid_usd: float) -> dict:
    return {
        "ts": position.opened_ts,
        "swing_ref": None,
        "fib_level": None,
        "gann_angle": None,
        "action": position.action,
        "rationale_text": f"bulk import from Binance Position History row {position.row_number} (closing_pnl={position.closing_pnl})",
        "leverage": None,
        "margin_mode": position.margin_mode,
        "entry_fill_price": position.entry_price,
        "exit_fill_price": position.exit_price,
        "fees_paid_usd": fees_paid_usd,
        "funding_paid_usd": None,
        "exit_reason_real": None,
    }


def _sql_literal(value) -> str:
    """None -> NULL, numbers as-is, strings single-quoted with embedded
    quotes doubled (standard SQL escaping) -- used for every value this
    module emits into generated SQL, not just ones a human typed, since
    CSV data (symbols, rationale text) could in principle contain a
    quote character and silently producing broken/injectable SQL from
    that would be a real bug, not just an edge case."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def generate_instrument_provision_sql(binance_symbols: list[str], venue: str) -> str:
    """Idempotent -- ON CONFLICT DO NOTHING against the same (venue_id,
    venue_symbol) unique constraint apps/products/trading/ingestion/
    ingest.py's upsert_instrument() relies on, so running this SQL twice
    (or against a venue that already has some of these instruments) is
    safe."""
    statements = []
    for binance_symbol in binance_symbols:
        instrument_symbol = to_instrument_symbol(binance_symbol)
        base_asset = binance_symbol[:-4]
        statements.append(
            "INSERT INTO instrument (venue_id, symbol, venue_symbol, base_asset, quote_asset, contract_type)\n"
            f"SELECT id, {_sql_literal(instrument_symbol)}, {_sql_literal(instrument_symbol)}, {_sql_literal(base_asset)}, 'USDT', 'perpetual'\n"
            f"FROM venue WHERE name = {_sql_literal(venue)}\n"
            "ON CONFLICT (venue_id, venue_symbol) DO NOTHING;"
        )
    return "\n".join(statements)


def generate_trade_annotation_insert_sql(rows_by_symbol: dict[str, list[dict]], venue: str) -> str:
    statements = []
    for binance_symbol, rows in rows_by_symbol.items():
        instrument_symbol = to_instrument_symbol(binance_symbol)
        instrument_sql = (
            "(SELECT i.id FROM instrument i JOIN venue v ON v.id = i.venue_id "
            f"WHERE v.name = {_sql_literal(venue)} AND i.venue_symbol = {_sql_literal(instrument_symbol)})"
        )
        for row in rows:
            columns = "instrument_id, ts, action, rationale_text, margin_mode, entry_fill_price, exit_fill_price, fees_paid_usd, leverage, exit_reason_real, funding_paid_usd"
            values = ", ".join(
                [
                    instrument_sql,
                    f"{_sql_literal(row['ts'].isoformat())}::timestamptz",
                    _sql_literal(row["action"]),
                    _sql_literal(row["rationale_text"]),
                    _sql_literal(row["margin_mode"]),
                    _sql_literal(row["entry_fill_price"]),
                    _sql_literal(row["exit_fill_price"]),
                    _sql_literal(row["fees_paid_usd"]),
                    _sql_literal(row["leverage"]),
                    _sql_literal(row["exit_reason_real"]),
                    _sql_literal(row["funding_paid_usd"]),
                ]
            )
            statements.append(f"INSERT INTO trade_annotation ({columns})\nVALUES ({values});")
    return "\n".join(statements)


def generate_sql(rows_by_symbol: dict[str, list[dict]], venue: str) -> str:
    """Wrapped in an explicit BEGIN/COMMIT so the whole import is one
    atomic unit regardless of the SQL client's own autocommit behavior."""
    total = sum(len(rows) for rows in rows_by_symbol.values())
    header = (
        f"-- Generated by import_binance_position_history.py --emit-sql\n"
        f"-- {total} trade_annotation rows across {len(rows_by_symbol)} instruments\n"
        f"-- Run this entire script in one Neon SQL Editor session (or any client that keeps one session/transaction open).\n"
        f"\nBEGIN;\n"
    )
    instrument_sql = generate_instrument_provision_sql(sorted(rows_by_symbol.keys()), venue)
    insert_sql = generate_trade_annotation_insert_sql(rows_by_symbol, venue)
    return f"{header}\n{instrument_sql}\n\n{insert_sql}\n\nCOMMIT;\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--position-history", required=True, help="path to Binance Futures Position History CSV")
    parser.add_argument("--trade-history", required=True, help="path to Binance Futures Trade History CSV (for fee aggregation)")
    parser.add_argument("--tz-offset-hours", type=float, required=True, help="UTC offset of the CSV timestamps, e.g. 7 for UTC+7/WIB")

    parser.add_argument("--venue", default="binance")
    parser.add_argument("--dry-run", action="store_true", help="print a summary + sample rows, touch nothing")
    parser.add_argument(
        "--emit-sql",
        metavar="PATH",
        help="write a .sql file (instrument provisioning + INSERTs, one transaction) instead of "
        "connecting to the DB directly -- for running by hand in the Neon SQL Editor or any client that keeps "
        "one session open. Needs no DATABASE_URL/sqlalchemy at all.",
    )
    return parser


def _preview_row(row: dict) -> dict:
    return {**row, "ts": row["ts"].isoformat()}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    positions = parse_position_history(args.position_history, args.tz_offset_hours)
    fills = parse_trade_history(args.trade_history, args.tz_offset_hours)

    rows_by_symbol: dict[str, list[dict]] = {}
    for position in positions:
        fees = sum_fees_for_position(fills, position)
        row = build_row(position, fees)
        rows_by_symbol.setdefault(position.symbol, []).append(row)

    total = sum(len(rows) for rows in rows_by_symbol.values())

    if args.dry_run:
        print(f"parsed {len(positions)} closed positions across {len(rows_by_symbol)} symbols, {len(fills)} trade fills loaded")
        print(f"total fees matched: ${sum(r['fees_paid_usd'] for rows in rows_by_symbol.values() for r in rows):.2f}")
        print("\nper-symbol counts:")
        for symbol, rows in sorted(rows_by_symbol.items(), key=lambda kv: -len(kv[1])):
            print(f"  {symbol:16s} {len(rows)}")
        print(f"\nsample (first 3 of {total}):")
        shown = 0
        for rows in rows_by_symbol.values():
            for row in rows:
                if shown >= 3:
                    break
                print(json.dumps(_preview_row(row), indent=2, default=str))
                shown += 1
            if shown >= 3:
                break
        print("\nDRY RUN -- nothing written. leverage/exit_reason_real/funding_paid_usd left NULL (see module docstring for why).")
        return 0

    if args.emit_sql:
        sql = generate_sql(rows_by_symbol, args.venue)
        with open(args.emit_sql, "w") as f:
            f.write(sql)
        print(f"wrote {args.emit_sql} ({total} trade_annotation INSERTs across {len(rows_by_symbol)} instruments)")
        print("run this entire file in one Neon SQL Editor session (or any client that keeps one session open) to execute it.")
        return 0

    from kinetiq_db.engine import normalize_db_url
    from kinetiq_db.models import Instrument, TradeAnnotation, Venue
    from sqlalchemy import create_engine, insert, select
    from sqlalchemy.orm import Session

    engine = create_engine(normalize_db_url(os.environ["DATABASE_URL"]))
    inserted = 0
    with Session(engine) as session, session.begin():
        venue_row = session.execute(select(Venue.id).where(Venue.name == args.venue)).first()
        if venue_row is None:
            raise SystemExit(f"no venue found named {args.venue!r} -- run ingestion for it first")
        venue_id = venue_row.id

        for binance_symbol, rows in rows_by_symbol.items():
            instrument_symbol = to_instrument_symbol(binance_symbol)
            inst_row = session.execute(select(Instrument.id).where(Instrument.venue_id == venue_id, Instrument.venue_symbol == instrument_symbol)).first()
            if inst_row is None:
                base_asset = binance_symbol[:-4]
                instrument_id = session.execute(
                    insert(Instrument)
                    .values(venue_id=venue_id, symbol=instrument_symbol, venue_symbol=instrument_symbol, base_asset=base_asset, quote_asset="USDT", contract_type="perpetual")
                    .returning(Instrument.id)
                ).scalar_one()
            else:
                instrument_id = inst_row.id

            for row in rows:
                session.execute(insert(TradeAnnotation).values(instrument_id=instrument_id, **row))
                inserted += 1

    print(f"inserted {inserted} trade_annotation rows across {len(rows_by_symbol)} instruments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
