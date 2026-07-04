"""Fase 5 (docs/sonnet5-implementation-roadmap.md): controlled A/B harness
for the R:R gate band and SL-placement variants, run over real per-series
candle data. NOT a production module other code imports -- this is the
"eksperimen terkontrol, bukan tuning diam-diam" harness itself, matching
the roadmap's explicit framing (unlike Fase 1-4, whose modules graduate
into permanent production code, F5's own deliverable is a walk-forward
comparison report; whichever variant (if any) should become the new
DEFAULT_* constant in fib_gann_timing.py is a separate, later human
decision, same "never auto-applies" precedent Fase 3's evaluate_adoption()
set).

Reuses generate_windows_by_calendar() (the SAME calendar walk-forward
scheme run_validation.py/the real Fase 1 campaign use) and metrics.
compute_metrics() (fee-aware, Fase 1) -- this experiment's numbers are
directly comparable to the real validation campaign's own, not a separate
ad-hoc methodology.

Runtime note: generate_signals() is O(n^2) per call (documented in
signal_runner.py) -- ~115s for one full year (8770 candles) of one series
in this sandbox. This harness calls generate_signals() ONCE per (series,
variant) over the FULL candle series (replicate.py's already-validated
equivalent-to-run_validation.py approach -- see validation/deep_dive_2026_07/
README.md's "Methodological note"), then buckets the resulting signals into
each calendar window's test range for OOS metrics -- NOT run_validation.py's
own per-window re-generation, which would call generate_signals() once per
window per variant (10x more calls, same result).
"""

import argparse
import dataclasses
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "strategy"))
sys.path.insert(0, os.path.dirname(__file__))

import fib_gann_timing as fgt  # noqa: E402
import metrics  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402
from kinetiq_backtest.types import WindowMode  # noqa: E402
from kinetiq_backtest.windowing import generate_windows_by_calendar  # noqa: E402

# data_loader is imported lazily inside main(), not at module level -- same
# reason run_validation.py defers it: it pulls in kinetiq_db/sqlalchemy, a
# DB-coupled dependency this module (and every test importing it) otherwise
# has none of.

# Fase 5's acceptance criterion (roadmap): "walk-forward OOS net-fees di
# >=2 aset x 2 venue" -- the same 4 series the July deep-dive replication
# already used (docs/validation-deep-dive-2026-07.md), so results are
# directly comparable to that prior work.
SERIES = (
    ("binance", "BTC/USDT:USDT"),
    ("bybit", "BTC/USDT:USDT"),
    ("binance", "ETH/USDT:USDT"),
    ("bybit", "ETH/USDT:USDT"),
)
TIMEFRAME = "1h"
CANDLE_LOAD_LIMIT = 100000

# Matches validation/configs/walk_forward_windows.yaml -- the real Fase 1
# campaign's own scheme, so this experiment's window boundaries are
# directly comparable to it, not a separate methodology.
TRAIN_MONTHS = 1
TEST_MONTHS = 1
EMBARGO_DAYS = 1
STEP_MONTHS = 1
WINDOW_MODE = WindowMode.ANCHORED

# Same Binance USDT-M VIP0 taker fees Fase 1 established as the real-money
# baseline (validation-deep-dive-2026-07.md F5) -- every PF number this
# harness reports is net of these, never gross-only.
FEE_ENTRY_FRACTION = 0.0005
FEE_EXIT_FRACTION = 0.0005
MAX_HOLDING_BARS = 20

PF_NET_THRESHOLD = 1.3  # design brief Section 7's own promotion threshold


@dataclasses.dataclass(frozen=True)
class Variant:
    name: str
    min_rr_threshold: float = fgt.DEFAULT_MIN_RR_THRESHOLD
    max_rr_threshold: float | None = None
    sl_atr_buffer_multiplier: float = fgt.DEFAULT_SL_ATR_BUFFER_MULTIPLIER
    sl_method: fgt.StopLossMethod = fgt.StopLossMethod.ATR_BUFFER


# R:R axis (holding SL at the existing default) + SL axis (holding R:R at
# the existing default) -- two single-factor sweeps, not a full cross
# product grid (standard A/B practice: isolate one axis's effect at a
# time; a full min_rr x max_rr x sl grid would be 4x3=12 combinations per
# series for no added interpretive value over these 6, given F5's own
# framing as a screening experiment ahead of F6's full campaign).
VARIANTS = (
    Variant(name="baseline_rr1.5_sl0.375atr"),  # current production defaults
    Variant(name="rr2.0_nocap", min_rr_threshold=2.0),
    Variant(name="rr1.5_cap5.0", max_rr_threshold=fgt.DEFAULT_MAX_RR_THRESHOLD),
    Variant(name="rr2.0_cap5.0", min_rr_threshold=2.0, max_rr_threshold=fgt.DEFAULT_MAX_RR_THRESHOLD),
    Variant(name="sl0.75atr", sl_atr_buffer_multiplier=0.75),
    Variant(name="sl1.0atr", sl_atr_buffer_multiplier=1.0),
    Variant(name="sl_next_fib_level", sl_method=fgt.StopLossMethod.NEXT_FIB_LEVEL),
)


@dataclasses.dataclass(frozen=True)
class WindowOutcome:
    window_id: int
    test_start: datetime.datetime
    test_end: datetime.datetime
    trade_count: int
    metrics: metrics.MetricsResult | None
    sl_hit_fraction: float | None  # fraction of non-censored trades exiting via STOP_LOSS


@dataclasses.dataclass(frozen=True)
class VariantResult:
    series: str
    variant: str
    total_signals: int
    windows: list[WindowOutcome]
    windows_passing_pf: int
    total_windows: int
    pooled_pf_net: float | None  # PF net computed over every window's trades pooled together
    pooled_pf_net_ci90: tuple[float, float] | None  # F6b I5: bootstrap 90% CI, see metrics.bootstrap_pf_net_ci()
    pooled_sl_hit_fraction: float | None


def _sl_hit_fraction(trades: list[ts.SimulatedTrade]) -> float | None:
    resolved = [t for t in trades if not t.label.censored]
    if not resolved:
        return None
    return sum(1 for t in resolved if t.label.outcome is fgt.BarrierOutcome.STOP_LOSS) / len(resolved)


def run_variant(series_name: str, variant: Variant, candles: list[fgt.Candle]) -> VariantResult:
    signals = sr.generate_signals(
        candles,
        min_rr_threshold=variant.min_rr_threshold,
        max_rr_threshold=variant.max_rr_threshold,
        sl_atr_buffer_multiplier=variant.sl_atr_buffer_multiplier,
        sl_method=variant.sl_method,
    )
    windows = generate_windows_by_calendar(
        start=candles[0].ts,
        end=candles[-1].ts,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        embargo_days=EMBARGO_DAYS,
        step_months=STEP_MONTHS,
        mode=WINDOW_MODE,
    )

    window_outcomes = []
    pooled_trades: list[ts.SimulatedTrade] = []
    for window in windows:
        window_candles = [c for c in candles if c.ts < window.test_end]
        test_signals = [s for s in signals if window.test_start <= s.ts < window.test_end]
        trades = ts.simulate_trades(test_signals, window_candles, [], MAX_HOLDING_BARS, FEE_ENTRY_FRACTION, FEE_EXIT_FRACTION)
        non_censored = [t for t in trades if not t.label.censored]
        window_metrics = metrics.compute_metrics(trades) if non_censored else None
        window_outcomes.append(
            WindowOutcome(
                window_id=window.window_id,
                test_start=window.test_start,
                test_end=window.test_end,
                trade_count=len(trades),
                metrics=window_metrics,
                sl_hit_fraction=_sl_hit_fraction(trades),
            )
        )
        pooled_trades.extend(trades)

    windows_passing = sum(
        1 for w in window_outcomes if w.metrics is not None and w.metrics.profit_factor_net is not None and w.metrics.profit_factor_net > PF_NET_THRESHOLD
    )
    pooled_non_censored = [t for t in pooled_trades if not t.label.censored]
    pooled_metrics = metrics.compute_metrics(pooled_trades) if pooled_non_censored else None

    return VariantResult(
        series=series_name,
        variant=variant.name,
        total_signals=len(signals),
        windows=window_outcomes,
        windows_passing_pf=windows_passing,
        total_windows=len(windows),
        pooled_pf_net=pooled_metrics.profit_factor_net if pooled_metrics else None,
        pooled_pf_net_ci90=metrics.bootstrap_pf_net_ci(pooled_trades) if pooled_non_censored else None,
        pooled_sl_hit_fraction=_sl_hit_fraction(pooled_trades),
    )


def _variant_result_to_dict(result: VariantResult) -> dict:
    return {
        "series": result.series,
        "variant": result.variant,
        "total_signals": result.total_signals,
        "total_windows": result.total_windows,
        "windows_passing_pf": result.windows_passing_pf,
        "pooled_pf_net": result.pooled_pf_net,
        "pooled_pf_net_ci90": list(result.pooled_pf_net_ci90) if result.pooled_pf_net_ci90 else None,
        "pooled_sl_hit_fraction": result.pooled_sl_hit_fraction,
        "windows": [
            {
                "window_id": w.window_id,
                "test_start": w.test_start.isoformat(),
                "test_end": w.test_end.isoformat(),
                "trade_count": w.trade_count,
                "profit_factor_net": w.metrics.profit_factor_net if w.metrics else None,
                "sl_hit_fraction": w.sl_hit_fraction,
            }
            for w in result.windows
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "docs", "validation-results", "rr_sl_experiment.json"))
    args = parser.parse_args(argv)

    import data_loader  # deferred: see the module-level comment for why

    all_results = []
    for venue, symbol in SERIES:
        candles = data_loader.load_candles(venue, symbol, TIMEFRAME, limit=CANDLE_LOAD_LIMIT)
        if not candles:
            print(f"no candles for {venue}/{symbol} -- skipping")
            continue
        series_name = f"{venue}_{symbol.split('/')[0]}"
        print(f"{series_name}: {len(candles)} candles, {candles[0].ts} .. {candles[-1].ts}")
        for variant in VARIANTS:
            result = run_variant(series_name, variant, candles)
            print(
                f"  {variant.name}: signals={result.total_signals} windows_passing_pf={result.windows_passing_pf}/{result.total_windows} "
                f"pooled_pf_net={result.pooled_pf_net} ci90={result.pooled_pf_net_ci90} pooled_sl_hit_fraction={result.pooled_sl_hit_fraction}"
            )
            all_results.append(result)

    with open(args.output, "w") as f:
        json.dump([_variant_result_to_dict(r) for r in all_results], f, indent=2)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
