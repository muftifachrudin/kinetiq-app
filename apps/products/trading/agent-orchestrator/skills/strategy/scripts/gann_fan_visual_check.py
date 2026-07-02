"""One-off CLI to sanity-check gann_fan_prices() against a real TradingView
chart -- see docs/fib-gann-validation-brief.md Section 2c, which requires
visual validation of the calibration before it's relied on anywhere.

Usage:
    python3 scripts/gann_fan_visual_check.py --venue binance \\
        --symbol "BTC/USDT:USDT" --timeframe 1h

Pulls the most recent candles for the given instrument, runs detect_swings(),
picks the last two confirmed swing points as the fan's anchor leg, and prints:
  1. The exact two anchor points (timestamp + price) -- draw a Gann Fan on
     TradingView from point A to point B using those same two coordinates.
  2. A table of this module's computed price for every angle at a handful of
     future bars -- read the price where TradingView's own angle lines sit at
     the matching bar/time and compare to the numbers below. They should
     match (small rounding aside); if they don't, the calibration is wrong.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, select  # noqa: E402

import fib_gann_timing as fgt  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../../../../packages/db/src"))
from kinetiq_db.engine import normalize_db_url  # noqa: E402
from kinetiq_db.models import Instrument, Ohlcv, Venue  # noqa: E402

PROJECTION_BAR_OFFSETS = (1, 2, 3, 5, 8, 13)


def load_candles(venue: str, symbol: str, timeframe: str, limit: int) -> list[fgt.Candle]:
    engine = create_engine(normalize_db_url(os.environ["DATABASE_URL"]))
    query = (
        select(Ohlcv.ts, Ohlcv.open, Ohlcv.high, Ohlcv.low, Ohlcv.close, Ohlcv.volume)
        .join(Instrument, Instrument.id == Ohlcv.instrument_id)
        .join(Venue, Venue.id == Instrument.venue_id)
        .where(Venue.name == venue, Instrument.symbol == symbol, Ohlcv.timeframe == timeframe)
        .order_by(Ohlcv.ts.desc())
        .limit(limit)
    )
    with engine.connect() as conn:
        rows = list(conn.execute(query))
    rows.reverse()
    return [
        fgt.Candle(
            ts=row.ts,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venue", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    candles = load_candles(args.venue, args.symbol, args.timeframe, args.limit)
    if len(candles) < 20:
        raise SystemExit(f"only {len(candles)} candles found -- need more history for a meaningful fan")

    swings = fgt.detect_swings(candles)
    if len(swings) < 2:
        raise SystemExit(f"only {len(swings)} swing(s) detected -- can't form an anchor leg")

    basis_leg_start, pivot = swings[-2], swings[-1]

    print(f"{args.venue} {args.symbol} {args.timeframe} -- {len(candles)} candles, {len(swings)} swings detected\n")
    print("Draw a Gann Fan on TradingView from point A to point B using these exact anchors:")
    print(f"  A (basis leg start): idx={basis_leg_start.index:3d}  ts={basis_leg_start.ts.isoformat()}  price={basis_leg_start.price:.2f}  ({basis_leg_start.direction.name})")
    print(f"  B (pivot / fan origin): idx={pivot.index:3d}  ts={pivot.ts.isoformat()}  price={pivot.price:.2f}  ({pivot.direction.name})")
    base_rate = fgt.gann_base_rate(pivot, basis_leg_start)
    print(f"\n  price_per_time_unit (1x1 rate) = {base_rate:.4f} price units / bar\n")

    print(f"{'bars after B':>14} | {'bar ts (approx)':>25} | " + " | ".join(f"{label:>8}" for label in fgt.GANN_ANGLES))
    print("-" * (14 + 3 + 25 + 3 + len(fgt.GANN_ANGLES) * 11))
    for offset in PROJECTION_BAR_OFFSETS:
        bar_index = pivot.index + offset
        prices = fgt.gann_fan_prices(pivot, basis_leg_start, bar_index)
        approx_ts = ""
        if bar_index < len(candles):
            approx_ts = candles[bar_index].ts.isoformat()
        row = " | ".join(f"{prices[label]:>8.2f}" for label in fgt.GANN_ANGLES)
        print(f"{offset:>14} | {approx_ts:>25} | {row}")

    print(
        "\nCompare each column's price to where TradingView's matching angle line sits "
        "at that bar. If they diverge beyond rounding, the calibration (design brief "
        "Section 2c) needs revisiting before this is relied on."
    )


if __name__ == "__main__":
    main()
