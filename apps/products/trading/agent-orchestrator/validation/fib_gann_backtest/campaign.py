"""Fase 6 (docs/sonnet5-implementation-roadmap.md): the full out-of-sample
validation campaign -- the "gerbang skor 6->7" promotion gate itself.

Runs BOTH the current production defaults AND Fase 5's recommended
candidate config (min_rr=2.0/max_rr=5.0/sl_atr_buffer=1.0) across all 4
series (BTC/ETH x Binance/Bybit), side by side -- neither is assumed
correct going in, same "let evidence decide" principle every prior phase
in this codebase follows (Fase 3's evaluate_adoption(), Fase 5's own A/B
harness). Promotion is evaluated PER SERIES independently (design brief
Section 7: "PF net > 1.3 di >=2/3 window, per seri"), not pooled across
series -- reuses rr_sl_experiment.py's exact walk-forward window/metrics
machinery so results are directly comparable to Fase 1/5's own numbers,
not a separate methodology.

"Semua faktor" (roadmap): every signal is generated WITH real
derivatives_context (Fase 4) wired in via generate_signals()'s
derivatives_records param -- CoinGlass Hobbyist daily data, same source
Fase 4 verified against.

"Fitted weights": Fase 3 found the ORIGINAL 6-factor fit did NOT clear the
adoption bar (median AUC 0.522 < 0.55). This campaign refits per series
with the EXPANDED factor set (fit_weights.ALL_CANDIDATE_FEATURE_NAMES --
Fase 3's six plus the sma candidate plus Fase 4's four derivatives
candidates) and REPORTS whether adoption criteria are newly met -- exactly
Fase 3's own "report, never auto-apply" discipline, not a new gating
mechanism. `fib_gann_timing.ConfluenceWeights` is unchanged by this
module; whether/how to wire a fitted-model gate into actual trade
filtering is a separate, later decision this module does not make.

Regime segmentation: a simple, undisputed "bear/range/bull" proxy off each
calendar month's realized price drift -- descriptive/reporting only, not
fed back into signal generation at all (no lookahead concern: this
classifies trades for a POST-HOC breakdown using the full month's
realized drift, the same non-causal freedom metrics.compute_metrics_by_
regime()'s own docstring assumes of its caller-supplied regime_of()).
"""

import dataclasses
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "strategy"))
sys.path.insert(0, os.path.dirname(__file__))

import derivatives_context as dc  # noqa: E402
import fib_gann_timing as fgt  # noqa: E402
import fit_weights as fw  # noqa: E402
import metrics  # noqa: E402
import rr_sl_experiment as exp  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402

# Design brief Section 7 / validation/configs/walk_forward_windows.yaml:
# "PF net > 1.3 di >=2/3 window" -- 0.6666 (not the rounded-up 0.6667) so
# exactly 4-of-6-style fractions read correctly, same reasoning that
# config file's own comment gives. At 10 windows this means >=7/10 passes
# (7/10=0.7 >= 0.6666; 6/10=0.6 does not).
PF_PASS_FRACTION = 0.6666

# Fase 6's own "bear/range/bull proxy drift bulanan" -- an initial,
# undisputed starting point (same "initial numbers are free" convention as
# every other new constant in this validation harness), not fitted.
BULL_DRIFT_THRESHOLD = 0.05
BEAR_DRIFT_THRESHOLD = -0.05

SERIES = (
    ("binance", "BTC/USDT:USDT", "BTC"),
    ("bybit", "BTC/USDT:USDT", "BTC"),
    ("binance", "ETH/USDT:USDT", "ETH"),
    ("bybit", "ETH/USDT:USDT", "ETH"),
)
TIMEFRAME = "1h"
CANDLE_LOAD_LIMIT = 100000


@dataclasses.dataclass(frozen=True)
class CampaignConfig:
    name: str
    min_rr_threshold: float = fgt.DEFAULT_MIN_RR_THRESHOLD
    max_rr_threshold: float | None = None
    sl_atr_buffer_multiplier: float = fgt.DEFAULT_SL_ATR_BUFFER_MULTIPLIER
    sl_method: fgt.StopLossMethod = fgt.StopLossMethod.ATR_BUFFER


# Neither is assumed correct -- both run through the same campaign so the
# real numbers decide, matching Fase 5's own A/B framing.
CAMPAIGN_CONFIGS = (
    CampaignConfig(name="current_defaults"),
    CampaignConfig(name="f5_candidate", min_rr_threshold=2.0, max_rr_threshold=5.0, sl_atr_buffer_multiplier=1.0),
)


def monthly_drift(candles: list[fgt.Candle]) -> dict[tuple[int, int], float]:
    """(year, month) -> realized price drift over that calendar month,
    using the first candle's open and the last candle's close seen for
    that month in this series. Descriptive/reporting only -- see module
    docstring on why using the full month's realized drift (not a
    causal/trailing-only figure) is fine here."""
    buckets: dict[tuple[int, int], list[fgt.Candle]] = {}
    for candle in candles:
        key = (candle.ts.year, candle.ts.month)
        buckets.setdefault(key, []).append(candle)
    return {key: (bucket[-1].close - bucket[0].open) / bucket[0].open for key, bucket in buckets.items()}


def classify_regime(drift: float) -> str:
    if drift > BULL_DRIFT_THRESHOLD:
        return "bull"
    if drift < BEAR_DRIFT_THRESHOLD:
        return "bear"
    return "range"


def regime_of_trade(trade: ts.SimulatedTrade, drift_by_month: dict[tuple[int, int], float]) -> str:
    key = (trade.signal_ts.year, trade.signal_ts.month)
    drift = drift_by_month.get(key)
    if drift is None:
        return "unknown"  # a signal month with no candle coverage at all -- shouldn't happen, but never crash a report over it
    return classify_regime(drift)


def direction_of_trade(trade: ts.SimulatedTrade) -> str:
    return "long" if trade.direction is fgt.TradeDirection.LONG else "short"


def direction_regime_breakdown(
    trades: list[ts.SimulatedTrade], drift_by_month: dict[tuple[int, int], float]
) -> dict[tuple[str, str], metrics.MetricsResult]:
    """F6b I2: slice pooled trades by (direction, regime) instead of regime
    alone -- the investigation that found BTC's "bull regime is worst"
    (compute_metrics_by_regime()'s own breakdown) is largely an artifact of
    mixing trend-aligned trades (bull+long, bear+short) with counter-trend
    trades (bull+short, bear+long) into one regime bucket. Each of the 6
    (direction, regime) combinations is computed independently via
    compute_metrics(), so a combination with zero non-censored trades is
    simply absent from the result rather than raising -- unlike compute_
    metrics_by_regime(), which assumes every regime key the caller passes
    in already has at least one non-censored trade."""
    groups: dict[tuple[str, str], list[ts.SimulatedTrade]] = {}
    for trade in trades:
        key = (direction_of_trade(trade), regime_of_trade(trade, drift_by_month))
        groups.setdefault(key, []).append(trade)
    return {key: metrics.compute_metrics(group) for key, group in groups.items() if any(not t.label.censored for t in group)}


@dataclasses.dataclass(frozen=True)
class FitReport:
    median_auc: float | None
    pooled_correlation: float | None
    adopted: bool  # same two-criteria test as fit_weights.evaluate_adoption(), applied to the expanded feature set


def run_fit_report(
    signals: list[sr.Signal], candles: list[fgt.Candle], windows, funding_events: list[ts.FundingEvent], max_holding_bars: int
) -> FitReport:
    """Refits per window with fit_weights.ALL_CANDIDATE_FEATURE_NAMES (Fase
    3's six + sma candidate + Fase 4's four derivatives candidates) and
    reports whether Fase 3's own adoption criteria are newly met -- never
    applies a gate, purely informational (module docstring).

    Takes the SAME `signals` run_series_campaign() already generated for
    this exact (series, config, derivatives_records) combination, rather
    than regenerating them here -- two real bugs this fixes at once: (1)
    a second call to generate_signals() without derivatives_records would
    leave every derivatives factor at its neutral default (constant across
    every signal), making them contribute nothing to the fit despite the
    whole point of this report being to check THEIR contribution; (2)
    generate_signals() is O(n^2) and expensive (~115s for one full year in
    this sandbox) -- recomputing it a second time per (series, config)
    would double this module's runtime for no reason, since the exact
    signals already exist.
    """
    labeled = fw.build_labeled_signals(signals, candles, funding_events, max_holding_bars)
    results = []
    for window in windows:
        train, test = fw.split_by_window(labeled, window)
        results.append(fw._fit_binary(train, test, feature_names=fw.ALL_CANDIDATE_FEATURE_NAMES))  # noqa: SLF001

    aucs = [r.auc for r in results if r.auc is not None]
    median_auc = statistics.median(aucs) if aucs else None

    pooled = [pair for r in results for pair in r.oos_predictions]
    correlation = None
    if len(pooled) >= 2:
        confidences = [p[0] for p in pooled]
        returns = [p[1] for p in pooled]
        if len(set(confidences)) > 1 and len(set(returns)) > 1:
            correlation = statistics.correlation(confidences, returns)

    adopted = median_auc is not None and median_auc > fw.ADOPTION_MIN_MEDIAN_AUC and correlation is not None and correlation > fw.ADOPTION_MIN_CORRELATION
    return FitReport(median_auc=median_auc, pooled_correlation=correlation, adopted=adopted)


@dataclasses.dataclass(frozen=True)
class SeriesCampaignResult:
    series: str
    config_name: str
    total_signals: int
    total_windows: int
    windows_passing_pf: int
    promoted: bool  # windows_passing_pf / total_windows >= PF_PASS_FRACTION
    pooled_pf_net: float | None
    pooled_pf_net_ci90: tuple[float, float] | None  # F6b I5: bootstrap 90% CI on pooled_pf_net, see bootstrap_pf_net_ci()
    regime_metrics: dict[str, metrics.MetricsResult]
    direction_regime_metrics: dict[tuple[str, str], metrics.MetricsResult]  # F6b I2
    fit_report: FitReport


def run_series_campaign(
    series_name: str,
    candles: list[fgt.Candle],
    config: CampaignConfig,
    derivatives_records: list[dc.DailyDerivativesRecord] | None = None,
) -> SeriesCampaignResult:
    signals = sr.generate_signals(
        candles,
        min_rr_threshold=config.min_rr_threshold,
        max_rr_threshold=config.max_rr_threshold,
        sl_atr_buffer_multiplier=config.sl_atr_buffer_multiplier,
        sl_method=config.sl_method,
        derivatives_records=derivatives_records,
    )
    windows = exp.generate_windows_by_calendar(
        start=candles[0].ts,
        end=candles[-1].ts,
        train_months=exp.TRAIN_MONTHS,
        test_months=exp.TEST_MONTHS,
        embargo_days=exp.EMBARGO_DAYS,
        step_months=exp.STEP_MONTHS,
        mode=exp.WINDOW_MODE,
    )

    pooled_trades: list[ts.SimulatedTrade] = []
    windows_passing = 0
    for window in windows:
        window_candles = [c for c in candles if c.ts < window.test_end]
        test_signals = [s for s in signals if window.test_start <= s.ts < window.test_end]
        trades = ts.simulate_trades(test_signals, window_candles, [], exp.MAX_HOLDING_BARS, exp.FEE_ENTRY_FRACTION, exp.FEE_EXIT_FRACTION)
        non_censored = [t for t in trades if not t.label.censored]
        if non_censored:
            window_metrics = metrics.compute_metrics(trades)
            if window_metrics.profit_factor_net is not None and window_metrics.profit_factor_net > exp.PF_NET_THRESHOLD:
                windows_passing += 1
        pooled_trades.extend(trades)

    pooled_non_censored = [t for t in pooled_trades if not t.label.censored]
    pooled_metrics = metrics.compute_metrics(pooled_trades) if pooled_non_censored else None
    pooled_pf_net_ci90 = metrics.bootstrap_pf_net_ci(pooled_trades) if pooled_non_censored else None

    drift_by_month = monthly_drift(candles)
    regime_metrics = {}
    direction_regime_metrics = {}
    if pooled_non_censored:
        regime_metrics = metrics.compute_metrics_by_regime(pooled_trades, lambda t: regime_of_trade(t, drift_by_month))
        direction_regime_metrics = direction_regime_breakdown(pooled_trades, drift_by_month)

    fit_report = run_fit_report(signals, candles, windows, [], exp.MAX_HOLDING_BARS)

    total_windows = len(windows)
    promoted = total_windows > 0 and (windows_passing / total_windows) >= PF_PASS_FRACTION

    return SeriesCampaignResult(
        series=series_name,
        config_name=config.name,
        total_signals=len(signals),
        total_windows=total_windows,
        windows_passing_pf=windows_passing,
        promoted=promoted,
        pooled_pf_net=pooled_metrics.profit_factor_net if pooled_metrics else None,
        pooled_pf_net_ci90=pooled_pf_net_ci90,
        regime_metrics=regime_metrics,
        direction_regime_metrics=direction_regime_metrics,
        fit_report=fit_report,
    )


def _result_to_dict(result: SeriesCampaignResult) -> dict:
    return {
        "series": result.series,
        "config_name": result.config_name,
        "total_signals": result.total_signals,
        "total_windows": result.total_windows,
        "windows_passing_pf": result.windows_passing_pf,
        "promoted": result.promoted,
        "pooled_pf_net": result.pooled_pf_net,
        "pooled_pf_net_ci90": list(result.pooled_pf_net_ci90) if result.pooled_pf_net_ci90 else None,
        "regime_metrics": {
            regime: {"trade_count": m.trade_count, "profit_factor_net": m.profit_factor_net} for regime, m in result.regime_metrics.items()
        },
        "direction_regime_metrics": {
            f"{direction}_{regime}": {"trade_count": m.trade_count, "profit_factor_net": m.profit_factor_net}
            for (direction, regime), m in result.direction_regime_metrics.items()
        },
        "fit_report": {
            "median_auc": result.fit_report.median_auc,
            "pooled_correlation": result.fit_report.pooled_correlation,
            "adopted": result.fit_report.adopted,
        },
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", default=os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "docs", "validation-results", "campaign.json")
    )
    args = parser.parse_args(argv)

    import data_loader  # deferred: see rr_sl_experiment.py's own comment for why

    all_results = []
    for venue, symbol, coin in SERIES:
        candles = data_loader.load_candles(venue, symbol, TIMEFRAME, limit=CANDLE_LOAD_LIMIT)
        if not candles:
            print(f"no candles for {venue}/{symbol} -- skipping")
            continue
        series_name = f"{venue}_{coin}"
        print(f"{series_name}: {len(candles)} candles, {candles[0].ts} .. {candles[-1].ts}")
        for config in CAMPAIGN_CONFIGS:
            result = run_series_campaign(series_name, candles, config)
            print(
                f"  {config.name}: signals={result.total_signals} promoted={result.promoted} "
                f"windows_passing_pf={result.windows_passing_pf}/{result.total_windows} pooled_pf_net={result.pooled_pf_net} "
                f"ci90={result.pooled_pf_net_ci90}"
            )
            all_results.append(result)

    with open(args.output, "w") as f:
        json.dump([_result_to_dict(r) for r in all_results], f, indent=2)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
