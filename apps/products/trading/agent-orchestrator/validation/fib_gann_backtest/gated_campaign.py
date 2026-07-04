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

import dataclasses
import os
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "strategy"))
sys.path.insert(0, os.path.dirname(__file__))

import campaign  # noqa: E402
import fit_weights as fw  # noqa: E402
import metrics  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402


@dataclasses.dataclass(frozen=True)
class GateConfig:
    name: str
    use_confidence_gate: bool = False
    confidence_percentile: float = 50.0  # keep signals with predicted P(TP) >= this percentile of TRAIN's own predictions
    use_trend_alignment_gate: bool = False
    trend_alignment_threshold: float = 0.5  # keep signals with sma_trend_bias_alignment strictly above this


# Neither gate is assumed to help going in -- all four run through the
# same campaign so the real numbers decide (module docstring).
GATE_CONFIGS = (
    GateConfig(name="no_gate"),
    GateConfig(name="confidence_only", use_confidence_gate=True),
    GateConfig(name="trend_alignment_only", use_trend_alignment_gate=True),
    GateConfig(name="both_gates", use_confidence_gate=True, use_trend_alignment_gate=True),
)


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


def apply_gates(train: list[fw.LabeledSignal], test: list[fw.LabeledSignal], gate_config: GateConfig) -> list[fw.LabeledSignal]:
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
    derivatives_records=None,
    funding_events=None,
    max_holding_bars: int = 20,
) -> GatedSeriesResult:
    signals = sr.generate_signals(candles, derivatives_records=derivatives_records)
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

    pooled_trades = []
    total_kept = 0
    windows_passing = 0
    for window in windows:
        train, test = fw.split_by_window(labeled, window)
        kept = apply_gates(train, test, gate_config)
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
