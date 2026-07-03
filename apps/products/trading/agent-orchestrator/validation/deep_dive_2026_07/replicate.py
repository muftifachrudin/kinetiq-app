"""Replicate the walk-forward validation on one series, dump per-trade detail.

Signals are generated ONCE over the full series (generate_signals is strictly
causal via its as_of walk, so per-window results are identical to run_window's
re-slicing, minus edge-censoring near test_end which this variant resolves
with more data -- strictly better, noted in the report).
"""
import sys, os, csv, json, datetime

# this script lives in agent-orchestrator/validation/deep_dive_2026_07/
AO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(AO, "skills/strategy"))
sys.path.insert(0, os.path.join(AO, "validation/fib_gann_backtest"))

import fib_gann_timing as fgt
import signal_runner as sr
import trade_simulator as ts
import metrics as mx
from kinetiq_backtest.windowing import generate_windows_by_calendar
from kinetiq_backtest.types import WindowMode

venue, asset = sys.argv[1], sys.argv[2]
fn = f"candles_{venue}_{asset}.csv"
candles = []
with open(fn) as f:
    for row in csv.DictReader(f):
        t = datetime.datetime.fromisoformat(row["ts"].replace(" ", "T"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        candles.append(fgt.Candle(ts=t, open=float(row["open"]), high=float(row["high"]),
                                  low=float(row["low"]), close=float(row["close"]), volume=float(row["volume"])))
candles.sort(key=lambda c: c.ts)
print(f"{venue} {asset}: {len(candles)} candles {candles[0].ts} -> {candles[-1].ts}", flush=True)

signals = sr.generate_signals(candles)
print(f"signals: {len(signals)}", flush=True)
trades = ts.simulate_trades(signals, candles, [], 20)

# windows: same scheme as run_validation (anchored, 1mo train, 1mo test, 1d embargo)
windows = generate_windows_by_calendar(
    start=candles[0].ts, end=candles[-1].ts,
    train_months=1, test_months=1, embargo_days=1, step_months=1,
    mode=WindowMode.ANCHORED)

sig_by_ts = {s.ts: s for s in signals}
by_window = []
for w in windows:
    wtr = [t for t in trades if w.test_start <= t.signal_ts < w.test_end]
    ncf = [t for t in wtr if not t.label.censored]
    m = mx.compute_metrics(wtr) if ncf else None
    by_window.append({
        "window_id": w.window_id, "test_start": w.test_start.isoformat(), "test_end": w.test_end.isoformat(),
        "trades": len(wtr),
        "pf_net": m.profit_factor_net if m else None,
        "sharpe_net": m.sharpe_net if m else None,
        "win": m.win_count if m else 0, "loss": m.loss_count if m else 0,
    })

rows = []
for t in trades:
    s = sig_by_ts[t.signal_ts]
    ep = s.exit_plan
    tp1 = ep.take_profits[0] if ep.take_profits else None
    sl = ep.stop_loss
    rows.append({
        "ts": s.ts.isoformat(), "index": s.index, "direction": s.direction.name,
        "entry": s.entry_price, "sl": sl, "tp1": tp1,
        "confidence": s.confidence,
        "structure": f"{s.structure_event.event_type.name}:{s.structure_event.break_direction.name}" if s.structure_event else None,
        "outcome": t.label.outcome.name if hasattr(t.label.outcome, "name") else str(t.label.outcome),
        "return_pct": t.label.return_pct, "bars_held": t.label.bars_held,
        "censored": t.label.censored,
        "rr": ep.risk_reward_ratio,
    })
out = {"venue": venue, "asset": asset, "n_candles": len(candles), "n_signals": len(signals),
       "windows": by_window, "trades": rows}
with open(f"result_{venue}_{asset}.json", "w") as f:
    json.dump(out, f)
print("windows:", json.dumps(by_window, indent=None)[:400], flush=True)
print("DONE", venue, asset, flush=True)
