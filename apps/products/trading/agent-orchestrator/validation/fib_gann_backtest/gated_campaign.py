"""Controlled experiment following the Fase 6 campaign's own investigation
(docs/sonnet5-implementation-roadmap.md Fase 6, docs/fib-gann-validation-
brief.md Section 27): BTC failed promotion in every config tested so far
despite the walk-forward-refit model (fit_weights.ALL_CANDIDATE_FEATURE_
NAMES) showing genuine out-of-sample ranking power (median AUC 0.54-0.71
for BTC) -- that ranking power is never actually used to filter which
signals get traded. Separately, a direction x regime breakdown showed
BTC's "bull regime is worst" finding is largely an artifact of mixing
trend-aligned trades (good: bull+long PF 1.20, bear+short PF 1.38) with
counter-trend trades (bad: bull+short PF 0.64, bear+long PF 0.61).

This module tests BOTH as controlled gates, independently and combined,
same "let evidence decide, never auto-apply" discipline as every prior
phase (Fase 3's evaluate_adoption(), Fase 5/6's A/B framing) -- a new
default is never picked here, only measured.

CONFIDENCE GATE: per walk-forward window, fits a LogisticRegression on
TRAIN-range signals only (same model fit_weights._fit_binary() already
performs, replicated here to get direct access to the fitted model object
for per-signal predict_proba, which SchemeResult's aggregate summary
doesn't expose) using fit_weights.ALL_CANDIDATE_FEATURE_NAMES. The keep/
reject cutoff is the given percentile of the TRAIN set's OWN predicted-
probability distribution -- derived purely from train data, so applying
it to filter TEST-range signals introduces no lookahead. A window whose
train data can't support a fit (too few samples, single outcome class --
same MIN_TRAIN_SAMPLES guard fit_weights.py uses) passes every signal
through unfiltered for that window rather than raising or silently
dropping the window.

TREND-ALIGNMENT GATE: keeps only signals whose sma_trend_bias_alignment
(htf_bias.py, Fase 2/3 candidate column -- found more informative than
swing-based htf_alignment by the July deep-dive's F9 finding) exceeds a
threshold -- i.e., only trades a signal's own direction actually agrees
with the higher-timeframe SMA trend. No per-window fitting needed (this
factor is already computed at signal-generation time), so no lookahead
concern at all.

DAILY-BIAS GATE (F6b I1(b), the LITERAL variant -- docs/sonnet5-
implementation-roadmap.md): keeps only signals whose daily_bias_alignment
(signal_runner.py, single-timeframe swing-based Daily bias, distinct from
the SMA proxy above) exceeds a threshold -- the founder's original theory
v2 pasal (b) itself ("LONG melawan downtrend Daily = premis trade
invalid"), not a stand-in for it. Same no-lookahead reasoning as the
trend-alignment gate: this factor is already computed causally at
signal-generation time, so filtering on it introduces nothing new.

REGIME-DIRECTION GATE (F6b I2 follow-up, pre-registered 2026-07-05):
campaign.direction_regime_breakdown() found BTC's "bull regime is worst"
finding is actually a clean, consistent split -- bull+short is always the
worst cell, bear+short always the best -- across both venues and both
CAMPAIGN_CONFIGS. trend_alignment_only already exploits this INDIRECTLY
via a continuous sma_trend_bias_alignment score threshold; this gate
operationalizes the SAME finding DIRECTLY: veto a SHORT signal outright
whenever it fires during a classified bull regime, LONG signals are never
touched. Hypothesis (pre-registered BEFORE running against real data):
this more surgical, direct veto could clear BTC's promotion threshold
where the indirect proxy gate (trend_alignment_only, best BTC/Bybit
result so far: PF net 1.228, 6/10 windows) fell short of >=7/10 -- but
this is a hypothesis to test, not an assumed win; report the real number
either way, same discipline as every other gate here.

Critically, regime classification for THIS gate can NOT reuse campaign.
monthly_drift()/classify_regime() as-is -- that classifier deliberately
uses each FULL calendar month's REALIZED drift for a post-hoc breakdown
(campaign.py's own module docstring: "non-causal freedom... assumes of
its caller-supplied regime_of()"), which is fine for a retrospective
report but would be genuine lookahead bias if used as a LIVE gate (a
trade taken on the 3rd of the month would "know" whether the rest of
that month turns out bullish). trailing_drift()/_regime_by_signal_index()
below reuse the exact same classify_regime() thresholds (+/-5%) for
comparability, but compute drift over a TRAILING lookback window ending
at (and using only candles up to) each signal's own ts -- causal by
construction, same guarantee sma_trend_bias_alignment/daily_bias_
alignment already provide.

SIZING MULTIPLIER (F6b I1(a)): a fundamentally different mechanism from
the three gates above -- instead of dropping signals, every kept signal is
RESIZED by a continuous multiplier derived from the same per-window
fitted confidence model the confidence gate uses (never a hard veto, per
the gate-vs-score standing principle in the F6b module docstring this
file's own header references). See size_multiplier()/run_sizing_series()
below and metrics.weighted_profit_factor() for how "PF tertimbang-size"
is computed net of fees/funding (SimulatedTrade.net_return_pct is already
both).

Reuses fit_weights.build_labeled_signals()/split_by_window() to fit the
confidence gate (full-hindsight-resolved outcomes for TRAIN, the same
convention fit_weights.py itself already uses for fitting purposes --
resolving whether a January trade eventually hit TP/SL using candles from
weeks later isn't lookahead into the DECISION itself, since every
feature going into the model is still computed strictly causally at
signal time; it only affects how many labels survive as non-censored).

PF/promotion measurement is a DIFFERENT concern and does NOT reuse those
hindsight-resolved trades directly -- once a window's surviving (post-
gate) signals are known, they are RE-simulated against candles restricted
to `< window.test_end` (campaign.py's own run_series_campaign() approach,
walk-forward-strict, no hindsight), so the PF-net/promoted numbers this
module reports are directly comparable to campaign.py's own Fase 6
figures. Mixing the two conventions in one PF number would have made
this module's "no_gate" baseline silently diverge from Fase 6's own
baseline for identical data -- caught by a sanity check before the real
4-series run (same "verify with real data before the expensive run"
discipline every prior phase has followed), not assumed correct from
synthetic tests alone.
"""

import bisect
import dataclasses
import datetime
import os
import statistics
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "strategy"))
sys.path.insert(0, os.path.dirname(__file__))

import campaign  # noqa: E402
import fib_gann_timing as fgt  # noqa: E402
import fit_weights as fw  # noqa: E402
import metrics  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402

# Same "monthly" cadence as campaign.py's own calendar-month drift, but
# expressed as a trailing day-count so it can be computed causally at any
# signal's own ts rather than only at calendar-month boundaries.
REGIME_LOOKBACK_DAYS = 30


@dataclasses.dataclass(frozen=True)
class GateConfig:
    name: str
    use_confidence_gate: bool = False
    confidence_percentile: float = 50.0  # keep signals with predicted P(TP) >= this percentile of TRAIN's own predictions
    use_trend_alignment_gate: bool = False
    trend_alignment_threshold: float = 0.5  # keep signals with sma_trend_bias_alignment strictly above this
    use_daily_bias_gate: bool = False
    daily_bias_threshold: float = 0.5  # keep signals with daily_bias_alignment (F6b I1(b), literal) strictly above this
    use_regime_direction_gate: bool = False  # F6b I2 follow-up: veto SHORT signals fired during a causally-classified bull regime


# Neither gate is assumed to help going in -- all run through the same
# campaign so the real numbers decide (module docstring). daily_bias_only
# is F6b I1(b)'s literal, pre-registered variant -- reported alongside
# (not instead of) trend_alignment_only, which already answered the SMA
# proxy question; both are kept so the comparison itself is visible in
# the same report ("laporkan juga yang kalah"). veto_short_bull is the I2
# follow-up (module docstring) -- reported alongside, not instead of, the
# indirect trend_alignment_only proxy it's compared against.
GATE_CONFIGS = (
    GateConfig(name="no_gate"),
    GateConfig(name="confidence_only", use_confidence_gate=True),
    GateConfig(name="trend_alignment_only", use_trend_alignment_gate=True),
    GateConfig(name="daily_bias_only", use_daily_bias_gate=True),
    GateConfig(name="both_gates", use_confidence_gate=True, use_trend_alignment_gate=True),
    GateConfig(name="veto_short_bull", use_regime_direction_gate=True),
)


def trailing_drift(candle_ts: list[datetime.datetime], candles: list[fgt.Candle], as_of_ts: datetime.datetime, lookback_days: int = REGIME_LOOKBACK_DAYS) -> float | None:
    """Causal regime proxy for GATING -- see module docstring ("REGIME-
    DIRECTION GATE") for why this can't just reuse campaign.monthly_drift().
    Realized price drift over the trailing `lookback_days` window ending at
    (and including) as_of_ts, using ONLY candles with ts <= as_of_ts.
    `candle_ts` is `[c.ts for c in candles]` -- passed in rather than
    recomputed so callers classifying many signals against the same series
    only build it once (bisect needs a plain sorted list, not Candle
    objects). None if there isn't at least `lookback_days` of history
    before as_of_ts yet (too early in the series to classify -- caller
    treats this as "unknown", never vetoed, same fallback precedent as
    every other gate's can't-decide case in this module)."""
    window_start = as_of_ts - datetime.timedelta(days=lookback_days)
    end_idx = bisect.bisect_right(candle_ts, as_of_ts) - 1
    if end_idx < 0:
        return None
    start_idx = bisect.bisect_left(candle_ts, window_start)
    if start_idx > end_idx or candle_ts[start_idx] > window_start:
        return None  # not enough trailing history yet
    start_candle, end_candle = candles[start_idx], candles[end_idx]
    if start_candle.open == 0:
        return None
    return (end_candle.close - start_candle.open) / start_candle.open


def regime_by_signal_index(signals: list[sr.Signal], candles: list[fgt.Candle], lookback_days: int = REGIME_LOOKBACK_DAYS) -> dict[int, str]:
    """signal.index -> "bull"/"bear"/"range" (campaign.classify_regime()'s
    own thresholds, reused for comparability with campaign.py's post-hoc
    breakdown), computed causally per trailing_drift() above. Signals too
    early in the series to have `lookback_days` of trailing history are
    simply absent from the result (caller/gate treats a missing key as
    "unknown", never vetoed)."""
    candle_ts = [c.ts for c in candles]
    result = {}
    for signal in signals:
        drift = trailing_drift(candle_ts, candles, signal.ts, lookback_days)
        if drift is not None:
            result[signal.index] = campaign.classify_regime(drift)
    return result


def _fit_confidence_model(train: list[fw.LabeledSignal]) -> tuple[LogisticRegression, np.ndarray] | None:
    """Same fit fit_weights._fit_binary() performs (same solver/l1_ratio/
    guards), but returns the model itself (plus its train feature matrix,
    needed for the percentile cutoff) instead of a summarized SchemeResult
    -- this experiment needs per-signal predictions, not aggregate
    AUC/Brier. Returns None when the guards fit_weights.py already
    documents (too few samples, single outcome class) mean no fit is
    possible; callers pass every signal through unfiltered in that case."""
    train_pairs = [(ls, fw._binary_label(ls.trade.label.outcome)) for ls in train]  # noqa: SLF001
    train_pairs = [(ls, y) for ls, y in train_pairs if y is not None]
    if len(train_pairs) < fw.MIN_TRAIN_SAMPLES:
        return None
    y_train = [y for _, y in train_pairs]
    if len(set(y_train)) < 2:
        return None
    x_train = np.array([fw._feature_vector(ls.signal, fw.ALL_CANDIDATE_FEATURE_NAMES) for ls, _ in train_pairs])  # noqa: SLF001
    model = LogisticRegression(solver="saga", l1_ratio=fw.DEFAULT_L1_RATIO, max_iter=1000)
    model.fit(x_train, y_train)
    if 1 not in list(model.classes_):
        return None  # TAKE_PROFIT never seen in training -- nothing to rank confidence against
    return model, x_train


def _predict_proba(model: LogisticRegression, signal: sr.Signal) -> float:
    x = np.array([fw._feature_vector(signal, fw.ALL_CANDIDATE_FEATURE_NAMES)])  # noqa: SLF001
    return float(model.predict_proba(x)[0][list(model.classes_).index(1)])


def apply_gates(
    train: list[fw.LabeledSignal],
    test: list[fw.LabeledSignal],
    gate_config: GateConfig,
    regime_by_index: dict[int, str] | None = None,
) -> list[fw.LabeledSignal]:
    """regime_by_index (regime_by_signal_index()'s output) is only needed
    when gate_config.use_regime_direction_gate is True -- every other gate
    ignores it, same optional-until-needed shape as every other gate-
    specific input this function already takes (e.g. train is unused
    unless use_confidence_gate)."""
    candidates = list(test)

    if gate_config.use_confidence_gate:
        fit = _fit_confidence_model(train)
        if fit is not None:
            model, x_train = fit
            train_probs = model.predict_proba(x_train)[:, list(model.classes_).index(1)]
            cutoff = float(np.percentile(train_probs, gate_config.confidence_percentile))
            candidates = [ls for ls in candidates if _predict_proba(model, ls.signal) >= cutoff]
        # else: train data can't support a fit this window -- pass everything through (module docstring)

    if gate_config.use_trend_alignment_gate:
        candidates = [ls for ls in candidates if ls.signal.sma_trend_bias_alignment > gate_config.trend_alignment_threshold]

    if gate_config.use_daily_bias_gate:
        candidates = [ls for ls in candidates if ls.signal.daily_bias_alignment > gate_config.daily_bias_threshold]

    if gate_config.use_regime_direction_gate:
        regimes = regime_by_index or {}
        candidates = [
            ls for ls in candidates if not (ls.signal.direction is fgt.TradeDirection.SHORT and regimes.get(ls.signal.index) == "bull")
        ]

    return candidates


@dataclasses.dataclass(frozen=True)
class GatedSeriesResult:
    series: str
    gate_name: str
    total_signals: int  # before any gate -- same across every gate_config for a given series
    total_kept: int  # after gating, summed across windows
    total_windows: int
    windows_passing_pf: int
    promoted: bool
    pooled_pf_net: float | None


def run_gated_series(
    series_name: str,
    candles,
    gate_config: GateConfig,
    campaign_config: campaign.CampaignConfig = campaign.CAMPAIGN_CONFIGS[0],
    derivatives_records=None,
    funding_events=None,
    max_holding_bars: int = 20,
) -> GatedSeriesResult:
    """campaign_config (F6b I1, docs/sonnet5-implementation-roadmap.md):
    which R:R/SL config generates the underlying signals BEFORE any gate is
    applied -- defaults to campaign.CAMPAIGN_CONFIGS[0] (current production
    defaults, this module's original behavior, so every pre-existing call
    site/test is unaffected), but I1's own pre-registered A/B runs this on
    TOP of campaign.CAMPAIGN_CONFIGS[1] (F5's candidate) instead, per the
    roadmap's explicit "di atas config kandidat F5" framing -- reusing
    campaign.CampaignConfig rather than a parallel set of loose R:R/SL
    params."""
    signals = sr.generate_signals(
        candles,
        min_rr_threshold=campaign_config.min_rr_threshold,
        max_rr_threshold=campaign_config.max_rr_threshold,
        sl_atr_buffer_multiplier=campaign_config.sl_atr_buffer_multiplier,
        sl_method=campaign_config.sl_method,
        derivatives_records=derivatives_records,
    )
    labeled = fw.build_labeled_signals(signals, candles, funding_events or [], max_holding_bars)
    windows = campaign.exp.generate_windows_by_calendar(
        start=candles[0].ts,
        end=candles[-1].ts,
        train_months=campaign.exp.TRAIN_MONTHS,
        test_months=campaign.exp.TEST_MONTHS,
        embargo_days=campaign.exp.EMBARGO_DAYS,
        step_months=campaign.exp.STEP_MONTHS,
        mode=campaign.exp.WINDOW_MODE,
    )
    # Computed once per series (not per window) -- trailing_drift() only
    # ever looks at candles <= a signal's own ts, so precomputing this
    # against the FULL candle list is still walk-forward-safe (no future
    # window's candles can affect an earlier signal's classification).
    regime_by_index = regime_by_signal_index(signals, candles) if gate_config.use_regime_direction_gate else {}

    pooled_trades = []
    total_kept = 0
    windows_passing = 0
    for window in windows:
        train, test = fw.split_by_window(labeled, window)
        kept = apply_gates(train, test, gate_config, regime_by_index=regime_by_index)
        total_kept += len(kept)

        # Gate SELECTION uses the hindsight-resolved labeled signals above
        # (fitting/filtering only reads each signal's own pre-computed
        # features, never its outcome) -- but the trade actually COUNTED
        # for PF/promotion is RE-simulated here against window-restricted
        # candles, matching campaign.py's own walk-forward-strict
        # convention exactly (module docstring).
        kept_signals = [ls.signal for ls in kept]
        window_candles = [c for c in candles if c.ts < window.test_end]
        trades = ts.simulate_trades(
            kept_signals, window_candles, funding_events or [], max_holding_bars, campaign.exp.FEE_ENTRY_FRACTION, campaign.exp.FEE_EXIT_FRACTION
        )
        non_censored = [t for t in trades if not t.label.censored]
        if non_censored:
            window_metrics = metrics.compute_metrics(trades)
            if window_metrics.profit_factor_net is not None and window_metrics.profit_factor_net > campaign.exp.PF_NET_THRESHOLD:
                windows_passing += 1
        pooled_trades.extend(trades)

    pooled_non_censored = [t for t in pooled_trades if not t.label.censored]
    pooled_metrics = metrics.compute_metrics(pooled_trades) if pooled_non_censored else None

    total_windows = len(windows)
    promoted = total_windows > 0 and (windows_passing / total_windows) >= campaign.PF_PASS_FRACTION

    return GatedSeriesResult(
        series=series_name,
        gate_name=gate_config.name,
        total_signals=len(signals),
        total_kept=total_kept,
        total_windows=total_windows,
        windows_passing_pf=windows_passing,
        promoted=promoted,
        pooled_pf_net=pooled_metrics.profit_factor_net if pooled_metrics else None,
    )


# --- F6b I1(a): sizing multiplier (module docstring) ---

# "dalam cap" -- confidence never vetoes a trade outright, only scales it
# within a bounded range; MIN_SIZE_MULTIPLIER=0.5/MAX=1.5 is a symmetric,
# undisputed starting band around the unscaled baseline of 1.0 (same
# "initial numbers are free, the fit/evidence decides whether it helps"
# convention as every other new constant in this harness -- not itself
# something Fase 3 fits).
MIN_SIZE_MULTIPLIER = 0.5
MAX_SIZE_MULTIPLIER = 1.5


def size_multiplier(confidence: float) -> float:
    """Linear map of a 0-1 confidence score to [MIN_SIZE_MULTIPLIER,
    MAX_SIZE_MULTIPLIER], clamped. confidence outside [0, 1] (shouldn't
    happen for a predict_proba output, but this is a pure function with no
    caller-trust assumption) is clamped first so the result never leaves
    the cap either."""
    clamped = max(0.0, min(1.0, confidence))
    return MIN_SIZE_MULTIPLIER + clamped * (MAX_SIZE_MULTIPLIER - MIN_SIZE_MULTIPLIER)


@dataclasses.dataclass(frozen=True)
class SizingConfig:
    name: str
    use_confidence_sizing: bool = False


# no_sizing (multiplier always 1.0) is the baseline every other variant is
# measured against -- same "let the number decide" discipline as
# GATE_CONFIGS' own no_gate entry.
SIZING_CONFIGS = (
    SizingConfig(name="no_sizing"),
    SizingConfig(name="confidence_sizing", use_confidence_sizing=True),
)


def _size_multipliers(train: list[fw.LabeledSignal], test: list[fw.LabeledSignal], sizing_config: SizingConfig) -> dict[int, float]:
    """signal.index -> multiplier for every signal in `test` -- keyed by
    index (not list position) since simulate_trades() can drop a signal
    entirely (the very last candle in the series has no forward data to
    label), and SimulatedTrade.signal_index is the stable join key back to
    whichever multiplier applies, regardless of any such drop."""
    if not sizing_config.use_confidence_sizing:
        return {ls.signal.index: 1.0 for ls in test}
    fit = _fit_confidence_model(train)
    if fit is None:
        return {ls.signal.index: 1.0 for ls in test}  # can't fit this window -- no scaling, same fallback precedent as the gate
    model, _ = fit
    return {ls.signal.index: size_multiplier(_predict_proba(model, ls.signal)) for ls in test}


@dataclasses.dataclass(frozen=True)
class SizingSeriesResult:
    series: str
    sizing_name: str
    total_signals: int
    total_windows: int
    pooled_pf_net: float | None  # unweighted (every trade at multiplier 1.0) -- directly comparable to campaign.py's own baseline
    pooled_weighted_pf_net: float | None  # size-weighted PF net, net of fees/funding (metrics.weighted_profit_factor)
    avg_multiplier: float | None  # funnel diagnostic: mean multiplier actually applied, across every non-censored trade
    min_multiplier: float | None
    max_multiplier: float | None


def run_sizing_series(
    series_name: str,
    candles,
    sizing_config: SizingConfig,
    campaign_config: campaign.CampaignConfig = campaign.CAMPAIGN_CONFIGS[0],
    derivatives_records=None,
    funding_events=None,
    max_holding_bars: int = 20,
) -> SizingSeriesResult:
    """campaign_config: see run_gated_series()'s own docstring -- same
    reasoning, same default, same I1 "on top of F5 candidate" override."""
    signals = sr.generate_signals(
        candles,
        min_rr_threshold=campaign_config.min_rr_threshold,
        max_rr_threshold=campaign_config.max_rr_threshold,
        sl_atr_buffer_multiplier=campaign_config.sl_atr_buffer_multiplier,
        sl_method=campaign_config.sl_method,
        derivatives_records=derivatives_records,
    )
    labeled = fw.build_labeled_signals(signals, candles, funding_events or [], max_holding_bars)
    windows = campaign.exp.generate_windows_by_calendar(
        start=candles[0].ts,
        end=candles[-1].ts,
        train_months=campaign.exp.TRAIN_MONTHS,
        test_months=campaign.exp.TEST_MONTHS,
        embargo_days=campaign.exp.EMBARGO_DAYS,
        step_months=campaign.exp.STEP_MONTHS,
        mode=campaign.exp.WINDOW_MODE,
    )

    pooled_trades: list[ts.SimulatedTrade] = []
    weighted_returns: list[tuple[float, float]] = []
    applied_multipliers: list[float] = []
    for window in windows:
        train, test = fw.split_by_window(labeled, window)
        multiplier_by_index = _size_multipliers(train, test, sizing_config)

        # Same walk-forward-strict re-simulation convention as apply_gates()
        # above (module docstring): sizing does not change WHICH signals
        # trade, only how much weight each gets, but PF is still measured
        # against window-restricted candles for direct comparability with
        # campaign.py/run_gated_series().
        test_signals = [ls.signal for ls in test]
        window_candles = [c for c in candles if c.ts < window.test_end]
        trades = ts.simulate_trades(
            test_signals, window_candles, funding_events or [], max_holding_bars, campaign.exp.FEE_ENTRY_FRACTION, campaign.exp.FEE_EXIT_FRACTION
        )
        for trade in trades:
            if not trade.label.censored:
                multiplier = multiplier_by_index[trade.signal_index]
                weighted_returns.append((multiplier, trade.net_return_pct))
                applied_multipliers.append(multiplier)
        pooled_trades.extend(trades)

    pooled_non_censored = [t for t in pooled_trades if not t.label.censored]
    pooled_metrics = metrics.compute_metrics(pooled_trades) if pooled_non_censored else None

    return SizingSeriesResult(
        series=series_name,
        sizing_name=sizing_config.name,
        total_signals=len(signals),
        total_windows=len(windows),
        pooled_pf_net=pooled_metrics.profit_factor_net if pooled_metrics else None,
        pooled_weighted_pf_net=metrics.weighted_profit_factor(weighted_returns) if weighted_returns else None,
        avg_multiplier=statistics.mean(applied_multipliers) if applied_multipliers else None,
        min_multiplier=min(applied_multipliers) if applied_multipliers else None,
        max_multiplier=max(applied_multipliers) if applied_multipliers else None,
    )


# --- CLI entrypoint (F6b I2 follow-up: veto_short_bull real 4-series run) ---
#
# Runs every GATE_CONFIGS entry against all 4 production series, on top of
# campaign.CAMPAIGN_CONFIGS[1] (F5's candidate: min_rr=2.0/max_rr=5.0/
# sl=1.0atr) -- matching I1's own established "di atas config kandidat F5"
# convention (docs/sonnet5-implementation-roadmap.md F6b), not production
# defaults, so results are directly comparable to I1's already-documented
# table. derivatives_records is intentionally left at its None default:
# veto_short_bull's mechanism (direction x causal-regime) never reads any
# derivatives factor, and per F6b's own "skor confidence tidak punya
# konsumen" finding, derivatives features don't influence which signals
# fire or their PF at all when the confidence/both_gates gates aren't in
# play for a given row -- this run reports every gate for comparability,
# but only veto_short_bull/no_gate/trend_alignment_only/daily_bias_only
# rows are unaffected by that omission either way.
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "docs", "validation-results", "gated_campaign.json"),
    )
    args = parser.parse_args()

    import data_loader  # deferred: see rr_sl_experiment.py's own comment for why

    f5_candidate = campaign.CAMPAIGN_CONFIGS[1]
    all_results = []
    for venue, symbol, coin in campaign.SERIES:
        candles = data_loader.load_candles(venue, symbol, campaign.TIMEFRAME, limit=campaign.CANDLE_LOAD_LIMIT)
        if not candles:
            print(f"no candles for {venue}/{symbol} -- skipping")
            continue
        series_name = f"{venue}_{coin}"
        print(f"{series_name}: {len(candles)} candles, {candles[0].ts} .. {candles[-1].ts}")
        for gate_config in GATE_CONFIGS:
            result = run_gated_series(series_name, candles, gate_config, campaign_config=f5_candidate)
            print(
                f"  {gate_config.name}: signals={result.total_signals} kept={result.total_kept} "
                f"promoted={result.promoted} windows_passing_pf={result.windows_passing_pf}/{result.total_windows} "
                f"pooled_pf_net={result.pooled_pf_net}"
            )
            all_results.append(dataclasses.asdict(result))

    with open(args.output, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"wrote {args.output}")
