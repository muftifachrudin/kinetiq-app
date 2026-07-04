import dataclasses
import datetime
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "validation" / "fib_gann_backtest"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402
import fit_weights as fw  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402
from kinetiq_backtest.types import WalkForwardWindow  # noqa: E402

UTC = datetime.timezone.utc
LONG = fgt.TradeDirection.LONG


def ts_at(hours: int) -> datetime.datetime:
    return datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=hours)


def mk(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(ts=ts_at(i), open=o, high=h, low=l, close=c, volume=v)


def mk_pivot(index: int) -> fgt.SwingPoint:
    return fgt.SwingPoint(index=index, ts=ts_at(index), price=100.0, direction=fgt.SwingDirection.LOW, wick_rejection_score=0.5)


def mk_signal(index: int, swing_quality: float = 0.5, direction: fgt.TradeDirection = LONG) -> sr.Signal:
    exit_plan = fgt.ExitPlan(
        direction=direction, entry_price=100.0, stop_loss=95.0, take_profits=(110.0,), risk_reward_ratio=2.0
    )
    pivot = mk_pivot(index)
    return sr.Signal(
        ts=ts_at(index),
        index=index,
        pivot=pivot,
        basis_leg_start=pivot,
        direction=direction,
        entry_price=100.0,
        exit_plan=exit_plan,
        confidence=0.5,
        structure_event=None,
        swing_quality=swing_quality,
        fib_gann_confluence=0.5,
        volume_confirmation=0.5,
        wick_rejection=0.5,
        structure_alignment=0.5,
        htf_alignment=0.5,
        regime_alignment=0.5,
    )


def mk_trade(signal: sr.Signal, outcome: fgt.BarrierOutcome, return_pct: float, censored: bool = False) -> ts.SimulatedTrade:
    label = fgt.TripleBarrierLabel(
        outcome=outcome, exit_price=100.0, exit_ts=signal.ts + datetime.timedelta(hours=5), bars_held=5,
        return_pct=return_pct, censored=censored,
    )
    return ts.SimulatedTrade(
        signal_ts=signal.ts, signal_index=signal.index, direction=signal.direction, confidence=signal.confidence,
        entry_price=signal.entry_price, label=label, funding_cost_pct=0.0, funding_events_count=0,
        fee_cost_pct=0.0, net_return_pct=return_pct,
    )


def mk_labeled(index: int, swing_quality: float, outcome: fgt.BarrierOutcome, return_pct: float, censored: bool = False) -> fw.LabeledSignal:
    signal = mk_signal(index, swing_quality=swing_quality)
    trade = mk_trade(signal, outcome, return_pct, censored=censored)
    return fw.LabeledSignal(signal=signal, trade=trade)


TP = fgt.BarrierOutcome.TAKE_PROFIT
SL = fgt.BarrierOutcome.STOP_LOSS
TIMEOUT = fgt.BarrierOutcome.TIMEOUT


# --- _feature_vector / _binary_label ---


def test_feature_vector_matches_feature_names_order():
    signal = mk_signal(0)
    vec = fw._feature_vector(signal)
    assert vec == [getattr(signal, name) for name in fw.FEATURE_NAMES]
    assert fw.FEATURE_NAMES == (
        "swing_quality", "fib_gann_confluence", "volume_confirmation", "wick_rejection", "structure_alignment", "htf_alignment",
        "sma_trend_bias_alignment",
    )


def test_binary_label_take_profit_is_one():
    assert fw._binary_label(TP) == 1


def test_binary_label_stop_loss_is_zero():
    assert fw._binary_label(SL) == 0


def test_binary_label_timeout_is_none():
    assert fw._binary_label(TIMEOUT) is None


# --- build_labeled_signals ---


def test_build_labeled_signals_excludes_signal_with_no_forward_candles():
    candles = [mk(i, 100, 101, 99, 100) for i in range(20)]
    signal_no_data = mk_signal(19)  # last candle in the series, no granular data at all
    labeled = fw.build_labeled_signals([signal_no_data], candles, funding_events=[], max_holding_bars=5)
    assert labeled == []  # simulate_trades() itself skips signals with no forward candles


def test_build_labeled_signals_drops_censored_but_keeps_resolved():
    # signal at index 1, 3 forward candles only -- with max_holding_bars=10,
    # this genuinely runs out of data before resolving -> censored TIMEOUT
    candles = [mk(i, 100, 101, 99, 100) for i in range(5)]
    signal = mk_signal(1)
    labeled = fw.build_labeled_signals([signal], candles, funding_events=[], max_holding_bars=10)
    assert labeled == []  # the only trade produced is censored -- must be excluded


def test_build_labeled_signals_keeps_genuine_resolution():
    candles = [mk(0, 100, 101, 99, 100)] + [mk(1, 100, 111, 96, 110)]  # bar 1 hits TP only, not SL(95)
    signal = mk_signal(0)
    labeled = fw.build_labeled_signals([signal], candles, funding_events=[], max_holding_bars=5)
    assert len(labeled) == 1
    assert labeled[0].trade.label.outcome is TP
    assert labeled[0].trade.label.censored is False


# --- split_by_window ---


def test_split_by_window_partitions_by_ts_range():
    w = WalkForwardWindow(window_id=0, train_start=ts_at(0), train_end=ts_at(10), test_start=ts_at(10), test_end=ts_at(20))
    labeled = [mk_labeled(i, 0.5, TP, 0.02) for i in [2, 5, 12, 15, 25]]
    train, test = fw.split_by_window(labeled, w)
    assert [ls.signal.index for ls in train] == [2, 5]
    assert [ls.signal.index for ls in test] == [12, 15]


# --- _fit_binary ---


def test_fit_binary_reports_skip_reason_when_too_few_train_samples():
    train = [mk_labeled(i, 0.9, TP, 0.02) for i in range(3)]
    result = fw._fit_binary(train, [])
    assert result.auc is None
    assert result.coefficients is None
    assert "train samples" in result.skip_reason


def test_fit_binary_reports_skip_reason_when_train_has_one_class_only():
    train = [mk_labeled(i, 0.9, TP, 0.02) for i in range(fw.MIN_TRAIN_SAMPLES + 5)]
    result = fw._fit_binary(train, [])
    assert result.auc is None
    assert "one outcome class" in result.skip_reason


def test_fit_binary_reports_skip_reason_when_test_set_too_small_but_still_reports_coefficients():
    rng = random.Random(1)
    train = []
    for i in range(30):
        quality = 0.9 if i % 2 == 0 else 0.1
        outcome = TP if rng.random() < (0.85 if quality > 0.5 else 0.15) else SL
        train.append(mk_labeled(i, quality, outcome, 0.02 if outcome is TP else -0.01))
    result = fw._fit_binary(train, [])
    assert result.coefficients is not None
    assert result.auc is None
    assert "test set" in result.skip_reason


def test_fit_binary_succeeds_with_informative_feature_and_reports_oos_predictions():
    rng = random.Random(7)

    def build(n, start_idx):
        out = []
        for j in range(n):
            i = start_idx + j
            quality = 0.9 if j % 2 == 0 else 0.1
            outcome = TP if rng.random() < (0.85 if quality > 0.5 else 0.15) else SL
            out.append(mk_labeled(i, quality, outcome, 0.03 if outcome is TP else -0.02))
        return out

    train = build(60, 0)
    test = build(20, 1000)
    result = fw._fit_binary(train, test)
    assert result.skip_reason is None
    assert result.auc is not None and 0.0 <= result.auc <= 1.0
    assert result.auc > 0.55  # swing_quality is genuinely informative in this synthetic set
    assert result.brier is not None
    assert len(result.oos_predictions) == len(test)
    for proba, net_return in result.oos_predictions:
        assert 0.0 <= proba <= 1.0


# --- _fit_three_class ---


def test_fit_three_class_reports_skip_reason_when_too_few_samples():
    train = [mk_labeled(i, 0.5, TP, 0.02) for i in range(3)]
    result = fw._fit_three_class(train, [])
    assert result.auc is None
    assert "train samples" in result.skip_reason


def test_fit_three_class_succeeds_with_all_three_outcomes_present():
    rng = random.Random(3)

    def build(n, start_idx):
        out = []
        for j in range(n):
            i = start_idx + j
            quality = rng.random()
            if quality > 0.66:
                outcome, ret = TP, 0.03
            elif quality > 0.33:
                outcome, ret = TIMEOUT, 0.0
            else:
                outcome, ret = SL, -0.02
            out.append(mk_labeled(i, quality, outcome, ret))
        return out

    train = build(60, 0)
    test = build(20, 1000)
    result = fw._fit_three_class(train, test)
    assert result.skip_reason is None
    assert result.auc is not None
    assert result.brier is not None
    assert result.coefficients is not None
    assert result.oos_predictions == []  # three_class never feeds the 3c adoption check


def test_fit_three_class_skips_when_test_has_unseen_class():
    train = [mk_labeled(i, 0.5, TP if i % 2 == 0 else SL, 0.01) for i in range(fw.MIN_TRAIN_SAMPLES + 5)]
    test = [mk_labeled(100 + i, 0.5, TIMEOUT, 0.0) for i in range(5)]  # TIMEOUT never seen in training
    result = fw._fit_three_class(train, test)
    assert result.auc is None
    assert "never seen in training" in result.skip_reason


# --- run_fit_weights (end-to-end) ---


def noisy_zigzag(n: int = 200, seed: int = 42) -> list[fgt.Candle]:
    rng = random.Random(seed)
    candles = []
    price = 100.0
    direction = -1
    for i in range(n):
        if i % 15 == 0:
            direction *= -1
        price += direction * rng.uniform(0.5, 2.0)
        o = price
        c = price + rng.uniform(-0.3, 0.3)
        h = max(o, c) + rng.uniform(0, 0.3)
        low = min(o, c) - rng.uniform(0, 0.3)
        candles.append(mk(i, o, h, low, c, v=100 + rng.uniform(-10, 10)))
        price = c
    return candles


def test_run_fit_weights_returns_one_result_per_window():
    candles = noisy_zigzag()
    windows = [
        WalkForwardWindow(window_id=0, train_start=ts_at(0), train_end=ts_at(80), test_start=ts_at(80), test_end=ts_at(140)),
        WalkForwardWindow(window_id=1, train_start=ts_at(0), train_end=ts_at(140), test_start=ts_at(140), test_end=ts_at(200)),
    ]
    results = fw.run_fit_weights(candles, windows, funding_events=[], max_holding_bars=20)
    assert len(results) == 2
    assert [r.window.window_id for r in results] == [0, 1]
    for r in results:
        assert r.train_count >= 0
        assert r.test_count >= 0
        assert isinstance(r.binary, fw.SchemeResult)
        assert isinstance(r.three_class, fw.SchemeResult)
        assert isinstance(r.binary_with_derivatives_candidate, fw.SchemeResult)
        # candidate variant's coefficients (when fit succeeds) must cover
        # exactly DERIVATIVES_FEATURE_NAMES, four extra keys vs the primary fit
        if r.binary_with_derivatives_candidate.coefficients is not None:
            assert set(r.binary_with_derivatives_candidate.coefficients) == set(fw.DERIVATIVES_FEATURE_NAMES)


def test_run_fit_weights_handles_window_with_no_candles():
    candles = noisy_zigzag(n=20)
    far_future_window = WalkForwardWindow(
        window_id=0, train_start=ts_at(10000), train_end=ts_at(10010), test_start=ts_at(10010), test_end=ts_at(10020)
    )
    results = fw.run_fit_weights(candles, [far_future_window], funding_events=[], max_holding_bars=20)
    assert len(results) == 1
    assert results[0].binary.skip_reason is not None
    assert results[0].three_class.skip_reason is not None
    assert results[0].binary_with_derivatives_candidate.skip_reason is not None


# --- DERIVATIVES_FEATURE_NAMES / derivatives candidate fit (Fase 4) ---


def mk_signal_with_derivatives(index: int, swing_quality: float, funding_contrarian_alignment: float) -> sr.Signal:
    signal = mk_signal(index, swing_quality=swing_quality)
    return dataclasses.replace(signal, funding_contrarian_alignment=funding_contrarian_alignment)


def test_derivatives_feature_names_appends_four_columns():
    assert fw.DERIVATIVES_FEATURE_NAMES == fw.FEATURE_NAMES + (
        "funding_contrarian_alignment",
        "global_ls_contrarian_alignment",
        "top_vs_global_alignment",
        "liq_cascade_flag",
    )


def test_fit_binary_with_derivatives_candidate_reports_four_more_coefficients():
    rng = random.Random(13)

    def build(n, start_idx):
        out = []
        for j in range(n):
            i = start_idx + j
            quality = 0.9 if j % 2 == 0 else 0.1
            outcome = TP if rng.random() < (0.85 if quality > 0.5 else 0.15) else SL
            signal = mk_signal_with_derivatives(i, swing_quality=quality, funding_contrarian_alignment=quality)
            trade = mk_trade(signal, outcome, 0.03 if outcome is TP else -0.02)
            out.append(fw.LabeledSignal(signal=signal, trade=trade))
        return out

    train = build(60, 0)
    test = build(20, 1000)
    primary = fw._fit_binary(train, test)
    candidate = fw._fit_binary(train, test, feature_names=fw.DERIVATIVES_FEATURE_NAMES)
    assert set(primary.coefficients) == set(fw.FEATURE_NAMES)
    assert set(candidate.coefficients) == set(fw.DERIVATIVES_FEATURE_NAMES)
    assert "funding_contrarian_alignment" in candidate.coefficients
    assert "funding_contrarian_alignment" not in primary.coefficients


# --- evaluate_adoption ---


def _mk_window_fit_result(window_id: int, auc: float | None, oos_predictions: list[tuple[float, float]]) -> fw.WindowFitResult:
    w = WalkForwardWindow(window_id=window_id, train_start=ts_at(0), train_end=ts_at(10), test_start=ts_at(10), test_end=ts_at(20))
    binary = fw.SchemeResult(auc=auc, brier=0.2 if auc is not None else None, coefficients={} if auc is not None else None, skip_reason=None if auc is not None else "skipped", oos_predictions=oos_predictions)
    empty = fw.SchemeResult(None, None, None, "not exercised in this test", [])
    return fw.WindowFitResult(window=w, train_count=10, test_count=len(oos_predictions), binary=binary, three_class=empty, binary_with_derivatives_candidate=empty)


def test_evaluate_adoption_not_adopted_when_no_valid_windows():
    decision = fw.evaluate_adoption([_mk_window_fit_result(0, None, [])])
    assert decision.adopted is False
    assert decision.median_binary_auc is None
    assert decision.pooled_oos_correlation is None


def test_evaluate_adoption_adopted_when_both_criteria_pass():
    # confidence and return move together across pooled OOS samples,
    # and every window's AUC clears the 0.55 threshold.
    predictions = [(0.9, 0.05), (0.8, 0.03), (0.2, -0.03), (0.1, -0.05), (0.6, 0.01), (0.4, -0.01)]
    results = [_mk_window_fit_result(0, 0.7, predictions), _mk_window_fit_result(1, 0.65, predictions)]
    decision = fw.evaluate_adoption(results)
    assert decision.median_binary_auc == pytest.approx(0.675)
    assert decision.pooled_oos_correlation is not None
    assert decision.pooled_oos_correlation > 0
    assert decision.adopted is True


def test_evaluate_adoption_not_adopted_when_auc_passes_but_correlation_does_not():
    # confidence and return move OPPOSITE -- negative correlation, matching
    # the deep-dive's actual baseline finding (r=-0.05) this criterion
    # exists to catch.
    predictions = [(0.9, -0.05), (0.8, -0.03), (0.2, 0.03), (0.1, 0.05), (0.6, -0.01), (0.4, 0.01)]
    results = [_mk_window_fit_result(0, 0.7, predictions)]
    decision = fw.evaluate_adoption(results)
    assert decision.median_binary_auc == pytest.approx(0.7)
    assert decision.pooled_oos_correlation is not None
    assert decision.pooled_oos_correlation < 0
    assert decision.adopted is False


def test_evaluate_adoption_not_adopted_when_correlation_passes_but_auc_does_not():
    predictions = [(0.9, 0.05), (0.8, 0.03), (0.2, -0.03), (0.1, -0.05)]
    results = [_mk_window_fit_result(0, 0.50, predictions)]  # below the 0.55 threshold
    decision = fw.evaluate_adoption(results)
    assert decision.pooled_oos_correlation > 0
    assert decision.adopted is False


def test_evaluate_adoption_pools_across_concatenated_series():
    # Fase 6b I3's formal sma_trend_bias_alignment adoption check
    # (docs/sonnet5-implementation-roadmap.md) was evaluated this same
    # way: this same function called on the CONCATENATION of multiple
    # series' own window_results lists -- no separate pooling function
    # needed.
    predictions = [(0.9, 0.05), (0.8, 0.03), (0.2, -0.03), (0.1, -0.05), (0.6, 0.01), (0.4, -0.01)]
    series_a = [_mk_window_fit_result(0, auc=0.6, oos_predictions=predictions)]
    series_b = [_mk_window_fit_result(0, auc=0.8, oos_predictions=predictions)]
    pooled_decision = fw.evaluate_adoption(series_a + series_b)
    assert pooled_decision.total_windows == 2
    assert pooled_decision.pooled_oos_sample_count == len(predictions) * 2
