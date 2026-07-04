"""Fase 3 of docs/sonnet5-implementation-roadmap.md: turns confidence
scoring from opinion into science by fitting weights against real
triple-barrier outcomes instead of relying on fib_gann_timing.
ConfluenceWeights' hand-tuned defaults (deep-dive F1: those defaults are
currently ANTI-predictive, pearson r=-0.05 against net_return_pct).

3a (per-factor dump): reads signal_runner.Signal's per-factor fields
directly (swing_quality, fib_gann_confluence, volume_confirmation,
wick_rejection, structure_alignment, htf_alignment, sma_trend_bias_
alignment) -- nothing here recomputes those, this module is purely a
consumer of the dump.

3b (fitting): refits a logistic regression PER walk-forward window --
trained ONLY on that window's train-range signals/outcomes, evaluated
ONLY on its test-range (out-of-sample). Never a single fit across the
whole series -- that would leak future information into what's reported
as "out-of-sample", exactly the caveat the deep-dive attached to its own
F10 combined-filter finding (in-sample, not yet walk-forward validated).

Two label schemes, BOTH reported (design brief: "kelola terpisah"):
 - binary: TAKE_PROFIT -> 1, STOP_LOSS -> 0, TIMEOUT excluded entirely
   (neither a clean win nor a clean loss -- forcing it into a 2-class
   fit would arbitrarily assign it a side it didn't earn).
 - three_class: TAKE_PROFIT/STOP_LOSS/TIMEOUT each their own class,
   using BarrierOutcome's own +1/-1/0 int values as labels directly.
Right-censored trades (label.censored) are excluded from BOTH -- their
eventual outcome is genuinely unknown, not a real TIMEOUT.

Regularization: LogisticRegression(solver="saga", l1_ratio=DEFAULT_L1_RATIO)
-- passing l1_ratio without an explicit `penalty` is scikit-learn's
current (>=1.8) way to request elastic-net (the old
penalty="elasticnet" spelling still works today but is deprecated and
warns). Elastic-net combines L1 (drives uninformative factors'
coefficients toward zero -- feature selection) and L2 (stabilizes
correlated factors) in one fit, rather than reporting two separate
models. l1_ratio is a starting default, not tuned, same "initial numbers
are free" convention as every other new constant introduced in this
validation harness (fib_gann_timing.DEFAULT_ZIGZAG_ATR_MULTIPLIER, etc).
No feature scaling: every factor is already a 0-1 score by construction
(same scale ConfluenceWeights' own inputs use), so raw coefficients stay
directly comparable without a StandardScaler.

regime_alignment is DELIBERATELY EXCLUDED from FEATURE_NAMES (though
still present on Signal and in any per-signal dump) -- signal_runner.py
currently feeds score_confluence()'s regime_alignment parameter the
exact same value as structure_alignment (market_structure.
structure_alignment_score()'s own output), so fitting on both would be
perfect collinearity for zero informational gain. If regime_alignment
ever diverges from structure_alignment (e.g. once market_regime.py,
PRD B.6, actually exists and starts feeding it something different),
promote it back into FEATURE_NAMES then.

3c (adoption criterion): evaluate_adoption() reports (never silently
applies) whether ConfluenceWeights' defaults SHOULD be replaced --
adopted=True only when BOTH hold, pooled across every window's
out-of-sample binary-scheme test signals:
 - median per-window binary AUC > ADOPTION_MIN_MEDIAN_AUC (0.55)
 - Pearson correlation(predicted P(TAKE_PROFIT), net_return_pct) >
   ADOPTION_MIN_CORRELATION (0.0) -- baseline hand-tuned ConfluenceWeights
   sits at r=-0.05 (deep-dive F1), so this is the same statistic on new
   ground, not a different metric.
The three_class scheme's AUC/Brier are reported for insight but do NOT
gate this decision -- the roadmap text doesn't disambiguate which scheme
the acceptance criterion applies to, and binary TP-vs-SL is the more
standard, directly comparable metric across windows. "Kalau tidak
tercapai, itu temuan valid — laporkan, jangan paksakan" applies
symmetrically: this module never mutates fib_gann_timing.ConfluenceWeights
itself; adopting a fitted result is a deliberate, separate follow-up
commit a human makes after reading this report.

sma_trend_bias_alignment -- OFFICIALLY ADOPTED into FEATURE_NAMES (Fase
6b I3, docs/sonnet5-implementation-roadmap.md, 3 Juli 2026): originally
Fase 2's deferred question (swing-based htf_alignment vs SMA-based
sma_trend_bias_alignment, which is the more informative HTF signal) was
answered by keeping it as a separate unblended CANDIDATE_FEATURE_NAMES
column and comparing coefficients side by side (Fase 3). That candidate
fit cleared evaluate_adoption()'s own two criteria (median AUC > 0.55 AND
correlation > 0) on a formal, pre-registered check -- individually on all
4 real series (BTC/ETH x Binance/Bybit: AUC 0.56-0.62, correlation all
positive 0.08-0.13) AND on the pooled-across-series sensitivity check
(AUC 0.583, correlation +0.116, n=1496) -- so it graduated into FEATURE_
NAMES directly; CANDIDATE_FEATURE_NAMES and the now-redundant informational-
only comparison fit no longer exist as separate concepts. This does NOT
by itself change fib_gann_timing.ConfluenceWeights/production signal
scoring -- that's still a distinct, later decision (see the "gate-vs-
skor" principle CLAUDE.md's F6b review recorded: a fitted-weights change
here has no live consumer to move PF at all without a gate/sizing
mechanism, e.g. F7a's PreTradeCard or the gated_campaign.py experiment).

derivatives candidate (Fase 4, docs/sonnet5-implementation-roadmap.md):
WindowFitResult.binary_with_derivatives_candidate is a SECOND, likewise
purely informational fit, using DERIVATIVES_FEATURE_NAMES (FEATURE_NAMES
plus derivatives_context.py's four direction-candidate columns:
funding_contrarian_alignment, global_ls_contrarian_alignment,
top_vs_global_alignment, liq_cascade_flag). These are dumped onto Signal
but never blended into ConfluenceWeights, so their coefficients only
become visible through a separate fit, never through the primary
adoption-gating one. A near-zero coefficient here is an expected, valid
outcome for at least liq_cascade_flag -- the July deep-dive already found
that whole OI/liq family to be "a coincident/volatility-regime indicator,
not a directional predictor... zero effect on trade outcomes" (CLAUDE.md)
-- this fit is what would make that concretely visible per-window rather
than asserted from memory. ALL_CANDIDATE_FEATURE_NAMES is now identical
to DERIVATIVES_FEATURE_NAMES (both = FEATURE_NAMES + the four derivatives
columns) since sma_trend_bias_alignment's promotion above removed the
distinction between "primary" and "sma-candidate" -- kept as its own name
since campaign.py/gated_campaign.py already reference it and its meaning
("every factor this codebase currently computes, in one fit") is still
useful on its own terms.

Depends on scikit-learn/numpy -- see packages/backtest-core/pyproject.toml's
[dev] extra comment for why that's validation-harness-only, never a
production service dependency.
"""

import dataclasses
import os
import statistics
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "strategy"))
sys.path.insert(0, os.path.dirname(__file__))

import derivatives_context as dc  # noqa: E402
import fib_gann_timing as fgt  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402
from kinetiq_backtest.types import WalkForwardWindow  # noqa: E402

FEATURE_NAMES = (
    "swing_quality",
    "fib_gann_confluence",
    "volume_confirmation",
    "wick_rejection",
    "structure_alignment",
    "htf_alignment",
    # Officially adopted (Fase 6b I3, 3 Juli 2026) -- see module docstring
    # for the pre-registered check this cleared. Formerly a separate
    # CANDIDATE_FEATURE_NAMES column; that distinction no longer exists.
    "sma_trend_bias_alignment",
)

# FEATURE_NAMES plus derivatives_context.py's four direction-candidate
# columns (Fase 4) -- see WindowFitResult.binary_with_derivatives_candidate
# in the module docstring. fuel_quadrant is intentionally absent: it's
# never dumped onto Signal at all (context/sizing only, not a direction
# feature -- derivatives_context.py's own module docstring).
DERIVATIVES_FEATURE_NAMES = FEATURE_NAMES + (
    "funding_contrarian_alignment",
    "global_ls_contrarian_alignment",
    "top_vs_global_alignment",
    "liq_cascade_flag",
)

# Same tuple as DERIVATIVES_FEATURE_NAMES today -- kept as its own name
# since campaign.py/gated_campaign.py already reference it (module
# docstring explains why).
ALL_CANDIDATE_FEATURE_NAMES = DERIVATIVES_FEATURE_NAMES

# Fewer usable (non-TIMEOUT, non-censored) train samples than this and a
# logistic fit is noise, not signal -- arbitrary-but-documented floor, not
# derived from a power calculation.
MIN_TRAIN_SAMPLES = 10
MIN_TEST_SAMPLES = 2

DEFAULT_L1_RATIO = 0.5

ADOPTION_MIN_MEDIAN_AUC = 0.55
ADOPTION_MIN_CORRELATION = 0.0


@dataclasses.dataclass(frozen=True)
class LabeledSignal:
    """One Signal joined to its simulated outcome -- the unit both the
    fitter and the 3c correlation check operate on."""

    signal: sr.Signal
    trade: ts.SimulatedTrade


def _feature_vector(signal: sr.Signal, feature_names: tuple[str, ...] = FEATURE_NAMES) -> list[float]:
    return [getattr(signal, name) for name in feature_names]


def build_labeled_signals(
    signals: list[sr.Signal],
    candles: list[fgt.Candle],
    funding_events: list[ts.FundingEvent],
    max_holding_bars: int,
) -> list[LabeledSignal]:
    """Simulates every signal and drops censored trades -- same
    right-censoring discipline metrics.py itself follows: a censored
    trade's eventual outcome is genuinely unknown, not a real TIMEOUT,
    so it must not enter either label scheme below."""
    trades = ts.simulate_trades(signals, candles, funding_events, max_holding_bars)
    by_index = {t.signal_index: t for t in trades}
    labeled = []
    for signal in signals:
        trade = by_index.get(signal.index)
        if trade is None or trade.label.censored:
            continue
        labeled.append(LabeledSignal(signal=signal, trade=trade))
    return labeled


def split_by_window(
    labeled: list[LabeledSignal], window: WalkForwardWindow
) -> tuple[list[LabeledSignal], list[LabeledSignal]]:
    train = [ls for ls in labeled if window.train_start <= ls.signal.ts < window.train_end]
    test = [ls for ls in labeled if window.test_start <= ls.signal.ts < window.test_end]
    return train, test


def _binary_label(outcome: fgt.BarrierOutcome) -> int | None:
    if outcome is fgt.BarrierOutcome.TAKE_PROFIT:
        return 1
    if outcome is fgt.BarrierOutcome.STOP_LOSS:
        return 0
    return None  # TIMEOUT -- excluded from the binary scheme entirely


@dataclasses.dataclass(frozen=True)
class SchemeResult:
    auc: float | None
    brier: float | None
    coefficients: dict[str, float] | None
    skip_reason: str | None
    # (predicted P(TAKE_PROFIT), net_return_pct) per out-of-sample test
    # signal -- only ever populated for the binary scheme (see module
    # docstring on why three_class doesn't feed the 3c adoption check).
    oos_predictions: list[tuple[float, float]]


def _multiclass_brier(y_true: list[int], proba: np.ndarray, classes: list[int]) -> float:
    """Standard multiclass Brier score: mean over samples of the sum over
    classes of (predicted_prob - actual_indicator)^2. Not in sklearn's
    brier_score_loss (binary-only), so implemented directly here."""
    total = 0.0
    for i, true_class in enumerate(y_true):
        for k, class_label in enumerate(classes):
            indicator = 1.0 if class_label == true_class else 0.0
            total += (proba[i, k] - indicator) ** 2
    return total / len(y_true)


def _fit_binary(train: list[LabeledSignal], test: list[LabeledSignal], feature_names: tuple[str, ...] = FEATURE_NAMES) -> SchemeResult:
    train_pairs = [(ls, _binary_label(ls.trade.label.outcome)) for ls in train]
    train_pairs = [(ls, y) for ls, y in train_pairs if y is not None]
    if len(train_pairs) < MIN_TRAIN_SAMPLES:
        return SchemeResult(None, None, None, f"only {len(train_pairs)} usable (non-TIMEOUT) train samples, need >= {MIN_TRAIN_SAMPLES}", [])

    y_train = [y for _, y in train_pairs]
    if len(set(y_train)) < 2:
        return SchemeResult(None, None, None, "train set has only one outcome class (all TAKE_PROFIT or all STOP_LOSS) -- nothing to fit", [])

    x_train = np.array([_feature_vector(ls.signal, feature_names) for ls, _ in train_pairs])
    model = LogisticRegression(solver="saga", l1_ratio=DEFAULT_L1_RATIO, max_iter=1000)
    model.fit(x_train, y_train)
    coefficients = dict(zip(feature_names, model.coef_[0].tolist(), strict=True))

    test_pairs = [(ls, _binary_label(ls.trade.label.outcome)) for ls in test]
    test_pairs = [(ls, y) for ls, y in test_pairs if y is not None]
    if len(test_pairs) < MIN_TEST_SAMPLES or len(set(y for _, y in test_pairs)) < 2:
        return SchemeResult(None, None, coefficients, f"test set has {len(test_pairs)} usable samples or only one class -- AUC/Brier undefined out-of-sample", [])

    x_test = np.array([_feature_vector(ls.signal, feature_names) for ls, _ in test_pairs])
    y_test = [y for _, y in test_pairs]
    proba_tp = model.predict_proba(x_test)[:, list(model.classes_).index(1)]
    auc = float(roc_auc_score(y_test, proba_tp))
    brier = float(np.mean((proba_tp - np.array(y_test)) ** 2))
    oos_predictions = [(float(p), ls.trade.net_return_pct) for p, (ls, _) in zip(proba_tp, test_pairs, strict=True)]
    return SchemeResult(auc=auc, brier=brier, coefficients=coefficients, skip_reason=None, oos_predictions=oos_predictions)


def _tp_coefficients(model: LogisticRegression) -> dict[str, float] | None:
    """Extracts the coefficient row for the TAKE_PROFIT (label 1) class,
    the one class both the binary and three_class schemes have in common
    -- lets SchemeResult.coefficients stay a single flat dict either way,
    rather than a differently-shaped structure per scheme. A binary fit's
    coef_ has exactly one row (sklearn's convention: it represents the
    higher of the two class labels), a genuine multiclass fit has one row
    per class in model.classes_ order. Returns None if label 1 was never
    present in the training data at all -- nothing to report."""
    classes = list(model.classes_)
    if 1 not in classes:
        return None
    if model.coef_.shape[0] == 1:
        if classes[1] != 1:
            return None  # the binary positive class isn't TAKE_PROFIT here
        row = model.coef_[0]
    else:
        row = model.coef_[classes.index(1)]
    return dict(zip(FEATURE_NAMES, row.tolist(), strict=True))


def _fit_three_class(train: list[LabeledSignal], test: list[LabeledSignal]) -> SchemeResult:
    if len(train) < MIN_TRAIN_SAMPLES:
        return SchemeResult(None, None, None, f"only {len(train)} train samples, need >= {MIN_TRAIN_SAMPLES}", [])

    y_train = [int(ls.trade.label.outcome) for ls in train]
    if len(set(y_train)) < 2:
        return SchemeResult(None, None, None, "train set has only one outcome class -- nothing to fit", [])

    x_train = np.array([_feature_vector(ls.signal) for ls in train])
    model = LogisticRegression(solver="saga", l1_ratio=DEFAULT_L1_RATIO, max_iter=1000)
    model.fit(x_train, y_train)
    coefficients = _tp_coefficients(model)

    y_test = [int(ls.trade.label.outcome) for ls in test]
    if test and not set(y_test) <= set(model.classes_):
        return SchemeResult(None, None, coefficients, "test set contains an outcome class never seen in training -- can't score it", [])
    if len(test) < MIN_TEST_SAMPLES or len(set(y_test)) < 2:
        return SchemeResult(None, None, coefficients, f"test set has {len(test)} samples or only one class -- AUC/Brier undefined out-of-sample", [])

    x_test = np.array([_feature_vector(ls.signal) for ls in test])
    classes = list(model.classes_)
    proba = model.predict_proba(x_test)
    try:
        auc = float(roc_auc_score(y_test, proba, multi_class="ovr", labels=classes))
    except ValueError as e:
        return SchemeResult(None, None, coefficients, f"multiclass AUC undefined: {e}", [])
    brier = _multiclass_brier(y_test, proba, classes)
    return SchemeResult(auc=auc, brier=brier, coefficients=coefficients, skip_reason=None, oos_predictions=[])


@dataclasses.dataclass(frozen=True)
class WindowFitResult:
    window: WalkForwardWindow
    train_count: int
    test_count: int
    binary: SchemeResult
    three_class: SchemeResult
    # Same binary TP-vs-SL scheme, fit on DERIVATIVES_FEATURE_NAMES (Fase
    # 4) -- purely informational, does NOT feed evaluate_adoption(). See
    # module docstring's "derivatives candidate" section.
    binary_with_derivatives_candidate: SchemeResult


def run_fit_weights(
    candles: list[fgt.Candle],
    windows: list[WalkForwardWindow],
    funding_events: list[ts.FundingEvent],
    max_holding_bars: int,
    derivatives_records: list[dc.DailyDerivativesRecord] | None = None,
) -> list[WindowFitResult]:
    """Per window: candles up to window.test_end feed generate_signals()
    (same no-lookahead convention run_validation.run_window() uses), then
    signals are split into train-range/test-range by ts, fit on train,
    evaluated on test. A window with zero candles gets an explicit
    skip_reason on both schemes, never a crash or a fabricated result.

    derivatives_records (Fase 4) is passed straight through to
    generate_signals() -- omitted (the default) leaves every derivatives
    Signal field at its neutral default, same backward-compatible
    behavior generate_signals() itself documents."""
    results = []
    for window in windows:
        window_candles = [c for c in candles if c.ts < window.test_end]
        if not window_candles:
            empty = SchemeResult(None, None, None, "no candles available before this window's test_end", [])
            results.append(
                WindowFitResult(
                    window=window,
                    train_count=0,
                    test_count=0,
                    binary=empty,
                    three_class=empty,
                    binary_with_derivatives_candidate=empty,
                )
            )
            continue

        signals = sr.generate_signals(window_candles, derivatives_records=derivatives_records)
        labeled = build_labeled_signals(signals, window_candles, funding_events, max_holding_bars)
        train, test = split_by_window(labeled, window)

        results.append(
            WindowFitResult(
                window=window,
                train_count=len(train),
                test_count=len(test),
                binary=_fit_binary(train, test),
                three_class=_fit_three_class(train, test),
                binary_with_derivatives_candidate=_fit_binary(train, test, feature_names=DERIVATIVES_FEATURE_NAMES),
            )
        )
    return results


@dataclasses.dataclass(frozen=True)
class AdoptionDecision:
    windows_with_valid_binary_fit: int
    total_windows: int
    median_binary_auc: float | None
    pooled_oos_correlation: float | None
    pooled_oos_sample_count: int
    adopted: bool


def evaluate_adoption(window_results: list[WindowFitResult]) -> AdoptionDecision:
    """3c: reports whether ConfluenceWeights' hand-tuned defaults should
    be replaced by a fitted result -- never applies that decision itself.
    See module docstring for exactly which two conditions must BOTH hold.

    window_results is a flat list with no special handling for which
    series/window each entry came from -- passing in the CONCATENATION of
    multiple series' own window_results lists pools the check across
    series (this is exactly how Fase 6b I3's formal sma_trend_bias_
    alignment adoption decision was evaluated, both per-series and
    pooled, before it graduated into FEATURE_NAMES -- see module
    docstring)."""
    binary_aucs = [wr.binary.auc for wr in window_results if wr.binary.auc is not None]
    median_auc = statistics.median(binary_aucs) if binary_aucs else None

    pooled = [pair for wr in window_results for pair in wr.binary.oos_predictions]
    correlation = None
    if len(pooled) >= 2:
        confidences = [p[0] for p in pooled]
        returns = [p[1] for p in pooled]
        if len(set(confidences)) > 1 and len(set(returns)) > 1:  # statistics.correlation requires non-zero variance
            correlation = statistics.correlation(confidences, returns)

    adopted = median_auc is not None and median_auc > ADOPTION_MIN_MEDIAN_AUC and correlation is not None and correlation > ADOPTION_MIN_CORRELATION

    return AdoptionDecision(
        windows_with_valid_binary_fit=len(binary_aucs),
        total_windows=len(window_results),
        median_binary_auc=median_auc,
        pooled_oos_correlation=correlation,
        pooled_oos_sample_count=len(pooled),
        adopted=adopted,
    )
