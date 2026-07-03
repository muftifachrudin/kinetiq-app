"""Design brief Section 6: run_validation.py -- CLI entrypoint wiring
data_loader -> signal_runner -> trade_simulator -> metrics across
packages/backtest-core's walk-forward windows (generate_windows_by_
calendar -- the calendar-duration scheme this harness uses per that
package's own docstring, not MARKOVIZ V5's candle-count scheme).

No warmup-window gymnastics: for window i, EVERY candle up to
window.test_end is fed to signal_runner.generate_signals() (already
strictly causal via its own as_of walk), then only signals whose ts
falls inside [window.test_start, window.test_end) are kept for that
window's metrics -- this reuses generate_signals()'s own no-lookahead
discipline for warmup instead of hand-tuning a separate buffer length.
A window with zero non-censored trades gets metrics=None, not a crash or
a fabricated zero -- run_validation() still counts it as NOT meeting the
PF threshold (a window that never traded hasn't demonstrated anything).

Checks ONLY the design brief Section 7's PF-based promotion criterion
(PF net > threshold in >= pf_pass_fraction of windows). The brief's OTHER
criterion -- "Agreement rate > 60% terhadap trade_annotation manual" --
is NOT computed here and is reported explicitly as not-yet-computable:
trade_annotation has no signal_id linkage to a specific generated signal
(see packages/db/migrations/versions/0005's docstring), so there is
nothing to compute agreement against yet.

--dry-run (brief: "CLI entrypoint, wajib support --dry-run"): loads
candles and generates the window set, prints a preview, and exits
WITHOUT running signal_runner/trade_simulator/metrics on any window and
WITHOUT writing a report file -- a safe way to check config/date-range
coverage before committing to a full run.
"""

import argparse
import dataclasses
import datetime
import os
import sys

import yaml
from kinetiq_backtest.types import WalkForwardWindow, WindowMode
from kinetiq_backtest.validators import validate_window_set
from kinetiq_backtest.windowing import generate_windows_by_calendar

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "strategy"))
sys.path.insert(0, os.path.dirname(__file__))

import fib_gann_timing as fgt  # noqa: E402
import metrics  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402

# data_loader (and report, below) are imported lazily inside main(), not at
# module level: data_loader pulls in kinetiq_db/sqlalchemy, a DB-coupled
# dependency this module otherwise has none of, same principle
# trade_simulator.py's own docstring states ("data_loader.py is a separate
# DB-touching module, deliberately kept out of anything this file imports")
# -- importing it eagerly here would force every test that imports this
# module (including ones that never call main()) to have sqlalchemy
# installed, which CI's `test` job deliberately does not.

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "walk_forward_windows.yaml")


def default_output_dir() -> str:
    """repo_root/docs/validation-results -- 6 ".." to reach repo root from
    .../apps/products/trading/agent-orchestrator/validation/fib_gann_backtest
    (a real bug caught only by computing this by hand, not by any existing
    test: every test so far passed an explicit --output-dir or used
    --dry-run, so a previous 5-".." version silently resolved to
    apps/docs/validation-results instead). Pulled into its own function so
    the resolution itself is directly testable, not just implicitly
    exercised by main()."""
    return os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "docs", "validation-results")


def safe_run_id_symbol(symbol: str) -> str:
    """ccxt-unified perp symbols look like "BTC/USDT:USDT" -- used as part
    of a filename (run_id), so every character invalid in a path needs
    stripping, not just "/". A real bug caught only by an actual CI run
    failing at the artifact-upload step (actions/upload-artifact, and
    Windows/NTFS generally, reject ":" outright) -- harmless on Linux
    locally, so nothing here would have caught it without that real run."""
    return symbol.replace("/", "-").replace(":", "-")


@dataclasses.dataclass(frozen=True)
class WindowResult:
    window: WalkForwardWindow
    signal_count: int
    trade_count: int
    metrics: metrics.MetricsResult | None  # None when there are zero non-censored trades in this window


@dataclasses.dataclass(frozen=True)
class ValidationRunResult:
    windows: list[WindowResult]
    total_windows: int
    windows_passing_pf: int
    pf_net_threshold: float
    pf_pass_fraction: float
    promotion_pf_criterion_met: bool


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def run_window(
    window: WalkForwardWindow,
    candles: list[fgt.Candle],
    funding_events: list[ts.FundingEvent],
    max_holding_bars: int,
) -> WindowResult:
    window_candles = [c for c in candles if c.ts < window.test_end]
    if not window_candles:
        return WindowResult(window=window, signal_count=0, trade_count=0, metrics=None)

    signals = sr.generate_signals(window_candles)
    test_signals = [s for s in signals if window.test_start <= s.ts < window.test_end]
    trades = ts.simulate_trades(test_signals, window_candles, funding_events, max_holding_bars)
    non_censored = [t for t in trades if not t.label.censored]

    window_metrics = metrics.compute_metrics(trades) if non_censored else None
    return WindowResult(window=window, signal_count=len(test_signals), trade_count=len(trades), metrics=window_metrics)


def _promotion_pf_stats(window_results: list[WindowResult], pf_net_threshold: float, pf_pass_fraction: float) -> tuple[int, bool]:
    """A window with metrics=None (zero non-censored trades) never counts
    as passing -- a window that produced no evidence hasn't demonstrated
    profitability, so it's conservatively treated as a failure for the
    promotion count, not excluded from the denominator."""
    passing = sum(
        1
        for wr in window_results
        if wr.metrics is not None and wr.metrics.profit_factor_net is not None and wr.metrics.profit_factor_net > pf_net_threshold
    )
    total = len(window_results)
    met = total > 0 and (passing / total) >= pf_pass_fraction
    return passing, met


def run_validation(
    candles: list[fgt.Candle],
    windows: list[WalkForwardWindow],
    funding_events: list[ts.FundingEvent],
    max_holding_bars: int,
    pf_net_threshold: float,
    pf_pass_fraction: float,
) -> ValidationRunResult:
    window_results = [run_window(w, candles, funding_events, max_holding_bars) for w in windows]
    passing, met = _promotion_pf_stats(window_results, pf_net_threshold, pf_pass_fraction)
    return ValidationRunResult(
        windows=window_results,
        total_windows=len(windows),
        windows_passing_pf=passing,
        pf_net_threshold=pf_net_threshold,
        pf_pass_fraction=pf_pass_fraction,
        promotion_pf_criterion_met=met,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--dry-run", action="store_true", help="preview windows without running the backtest or writing a report")
    parser.add_argument("--output-dir", default=default_output_dir())
    args = parser.parse_args(argv)

    import data_loader  # deferred: see the module-level comment for why

    config = load_config(args.config)
    candles = data_loader.load_candles(config["venue"], config["symbol"], config["timeframe"], limit=config.get("candle_load_limit", 100000))
    if not candles:
        print("no candles loaded -- check DATABASE_URL / venue/symbol/timeframe in the config")
        return 1

    wf = config["walk_forward"]
    windows = generate_windows_by_calendar(
        start=candles[0].ts,
        end=candles[-1].ts,
        train_months=wf["train_months"],
        test_months=wf["test_months"],
        embargo_days=wf.get("embargo_days", 0),
        step_months=wf.get("step_months"),
        mode=WindowMode(wf.get("mode", "anchored")),
    )

    print(f"loaded {len(candles)} candles, {candles[0].ts} .. {candles[-1].ts}")
    print(f"generated {len(windows)} walk-forward window(s)")
    for w in windows:
        print(f"  window {w.window_id}: train [{w.train_start} .. {w.train_end}) test [{w.test_start} .. {w.test_end})")
    if not windows:
        print("0 windows -- date range too short for train_months + test_months + embargo_days, nothing to run")

    if args.dry_run:
        return 0
    if not windows:
        return 1

    validate_window_set(windows, embargo=datetime.timedelta(days=wf.get("embargo_days", 0)))

    promo = config.get("promotion", {})
    result = run_validation(
        candles,
        windows,
        funding_events=[],
        max_holding_bars=config.get("max_holding_bars", 20),
        pf_net_threshold=promo.get("pf_net_threshold", 1.3),
        pf_pass_fraction=promo.get("pf_pass_fraction", 4 / 6),
    )

    import report  # deferred: only needed on the non-dry-run path

    run_id = f"{safe_run_id_symbol(config['symbol'])}_{config['timeframe']}_{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}"
    json_path, md_path = report.write_report(result, args.output_dir, run_id)
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(f"promotion PF criterion met: {result.promotion_pf_criterion_met} ({result.windows_passing_pf}/{result.total_windows} windows)")
    print("promotion agreement-rate criterion: not computable yet (trade_annotation has no signal_id linkage)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
