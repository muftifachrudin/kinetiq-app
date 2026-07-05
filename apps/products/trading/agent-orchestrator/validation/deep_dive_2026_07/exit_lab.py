"""Exit-management lab (deep-dive round 2, 4 Jul 2026): replay every
recorded trade under alternative exit rules and fee models.

Reads result_{venue}_{ASSET}.json + candles_{venue}_{ASSET}.csv from the
cwd (produced by pull_data.py + replicate.py). One-off analysis script,
not production code -- see README.md in this folder.

Conservative same-candle rule everywhere: if a bar touches both the
active stop and the target, count the stop. Managed stops (breakeven /
momentum exit) only act on bar CLOSES, and a ratcheted stop is only
checkable from the NEXT bar (no intra-bar lookahead).

Variants (combinable via CLI):
  --be X       move stop to entry once a bar closes >= X*R in favor
  --mom X      exit at close if a bar closes <= -X*R against the trade
  --tp-mult M  scale TP1 distance by M (0.7 = closer, 1.5 = farther)
  --max-hold N timeout bars (default 20, matching the harness)
  --fees tt|mm taker-taker vs maker-entry+maker-TP (stop/mom/timeout
               exits always pay taker; Binance VIP0: taker 5bps, maker 2bps)

Reports PF net + bootstrap CI90 for: all trades, per asset, and the
"stack" subset (SMA200-aligned & rr in [2,5) -- the causal combo from
the round-1 deep-dive).
"""

import argparse
import csv
import json
import random
import statistics

FEE_TAKER = 0.0005
FEE_MAKER = 0.0002
SERIES = [(v, a) for v in ("binance", "bybit") for a in ("BTC", "ETH")]


def pf(returns):
    gains = sum(r for r in returns if r > 0)
    losses = -sum(r for r in returns if r < 0)
    return gains / losses if losses > 0 else None


def load_candles(venue, asset):
    with open(f"candles_{venue}_{asset}.csv") as f:
        rows = list(csv.DictReader(f))
    return [(float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])) for r in rows]


def replay(trade, candles, args):
    entry = trade["entry"]
    stop = trade["sl"]
    take_profit = entry + (trade["tp1"] - entry) * args.tp_mult
    is_long = trade["direction"] == "LONG"
    sign = 1.0 if is_long else -1.0
    risk = abs(entry - trade["sl"])
    be_armed = False
    sequence = candles[trade["index"] + 1 : trade["index"] + 1 + args.max_hold]
    if not sequence:
        return None

    def net(gross, exit_kind):
        if args.fees == "tt":
            return gross - 2 * FEE_TAKER
        exit_fee = FEE_MAKER if exit_kind == "tp" else FEE_TAKER
        return gross - FEE_MAKER - exit_fee

    for _open, high, low, close in sequence:
        stop_hit = low <= stop if is_long else high >= stop
        tp_hit = high >= take_profit if is_long else low <= take_profit
        if stop_hit:
            return net(sign * (stop - entry) / entry, "stop")
        if tp_hit:
            return net(sign * (take_profit - entry) / entry, "tp")
        favorable = sign * (close - entry)
        if args.be is not None and not be_armed and favorable >= args.be * risk:
            stop = entry
            be_armed = True
        if args.mom is not None and favorable <= -args.mom * risk:
            return net(sign * (close - entry) / entry, "mom")
    return net(sign * (sequence[-1][3] - entry) / entry, "timeout")


def bootstrap_ci(values, iterations=3000, seed=42):
    rng = random.Random(seed)
    stats = []
    for _ in range(iterations):
        sample = [values[rng.randrange(len(values))] for _ in values]
        p = pf(sample)
        if p is not None:
            stats.append(p)
    stats.sort()
    return stats[int(0.05 * len(stats))], stats[int(0.95 * len(stats))]


def report(label, values):
    if len(values) < 10:
        print(f"{label}: n={len(values)} (too small)")
        return
    lo, hi = bootstrap_ci(values)
    print(f"{label}: n={len(values)} PF={pf(values):.3f} CI90=[{lo:.3f},{hi:.3f}] "
          f"mean={statistics.mean(values) * 100:+.3f}%")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--be", type=float, default=None)
    parser.add_argument("--mom", type=float, default=None)
    parser.add_argument("--tp-mult", type=float, default=1.0)
    parser.add_argument("--max-hold", type=int, default=20)
    parser.add_argument("--fees", choices=["tt", "mm"], default="tt")
    args = parser.parse_args(argv)

    rows = []
    for venue, asset in SERIES:
        with open(f"result_{venue}_{asset}.json") as f:
            data = json.load(f)
        candles = load_candles(venue, asset)
        for trade in data["trades"]:
            if trade["censored"]:
                continue
            i = trade["index"]
            closes = [c[3] for c in candles[max(0, i - 199) : i + 1]]
            sma200 = sum(closes) / len(closes)
            aligned = (trade["direction"] == "LONG") == (candles[i][3] > sma200)
            result = replay(trade, candles, args)
            if result is None:
                continue
            rows.append({"asset": asset, "aligned": aligned, "rr": trade["rr"], "net": result})

    print(f"config: be={args.be} mom={args.mom} tp_mult={args.tp_mult} "
          f"max_hold={args.max_hold} fees={args.fees}")
    report("ALL", [r["net"] for r in rows])
    for asset in ("BTC", "ETH"):
        report(asset, [r["net"] for r in rows if r["asset"] == asset])
    stack = [r for r in rows if r["aligned"] and r["rr"] and 2 <= r["rr"] < 5]
    report("STACK aligned&rr[2,5)", [r["net"] for r in stack])
    for asset in ("BTC", "ETH"):
        report(f"STACK {asset}", [r["net"] for r in stack if r["asset"] == asset])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
