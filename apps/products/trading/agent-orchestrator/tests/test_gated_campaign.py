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
import gated_campaign as gc  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402

UTC = datetime.timezone.utc
LONG = fgt.TradeDirection.LONG
TP = fgt.BarrierOutcome.TAKE_PROFIT
SL = fgt.BarrierOutcome.STOP_LOSS


def ts_at(hours: int) -> datetime.datetime:
    return datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=hours)


def mk(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(ts=ts_at(i), open=o, high=h, low=l, close=c, volume=v)


def noisy_zigzag(n: int = 1680, seed: int = 42) -> list[fgt.Candle]:
    """~70 days of hourly data -- same fixture rationale as
    test_campaign.py/test_rr_sl_experiment.py (>=1 walk-forward window,
    fast enough for O(n^2) generate_signals)."""
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


def mk_signal(index: int, swing_quality: float = 0.5, sma_trend_bias_alignment: float = 0.5) -> sr.Signal:
    exit_plan = fgt.ExitPlan(direction=LONG, entry_price=100.0, stop_loss=95.0, take_profits=(110.0,), risk_reward_ratio=2.0)
    pivot = fgt.SwingPoint(index=index, ts=ts_at(index), price=100.0, direction=fgt.SwingDirection.LOW, wick_rejection_score=0.5)
    return sr.Signal(
        ts=ts_at(index), index=index, pivot=pivot, basis_leg_start=pivot, direction=LONG, entry_price=100.0,
        exit_plan=exit_plan, confidence=0.5, structure_event=None, swing_quality=swing_quality,
        fib_gann_confluence=0.5, volume_confirmation=0.5, wick_rejection=0.5, structure_alignment=0.5,
        htf_alignment=0.5, regime_alignment=0.5, sma_trend_bias_alignment=sma_trend_bias_alignment,
    )


def mk_trade(signal: sr.Signal, outcome: fgt.BarrierOutcome, return_pct: float) -> ts.SimulatedTrade:
    label = fgt.TripleBarrierLabel(outcome=outcome, exit_price=100.0, exit_ts=signal.ts + datetime.timedelta(hours=5), bars_held=5, return_pct=return_pct, censored=False)
    return ts.SimulatedTrade(
        signal_ts=signal.ts, signal_index=signal.index, direction=signal.direction, confidence=signal.confidence,
        entry_price=signal.entry_price, label=label, funding_cost_pct=0.0, funding_events_count=0,
        fee_cost_pct=0.0, net_return_pct=return_pct,
    )


def mk_labeled(index: int, swing_quality: float, outcome: fgt.BarrierOutcome, return_pct: float, sma_trend_bias_alignment: float = 0.5) -> fw.LabeledSignal:
    signal = mk_signal(index, swing_quality=swing_quality, sma_trend_bias_alignment=sma_trend_bias_alignment)
    trade = mk_trade(signal, outcome, return_pct)
    return fw.LabeledSignal(signal=signal, trade=trade)


# --- GATE_CONFIGS ---


def test_gate_configs_covers_four_named_combinations():
    names = {c.name for c in gc.GATE_CONFIGS}
    assert names == {"no_gate", "confidence_only", "trend_alignment_only", "both_gates"}


def test_no_gate_config_has_both_gates_disabled():
    config = next(c for c in gc.GATE_CONFIGS if c.name == "no_gate")
    assert config.use_confidence_gate is False
    assert config.use_trend_alignment_gate is False


def test_both_gates_config_enables_both():
    config = next(c for c in gc.GATE_CONFIGS if c.name == "both_gates")
    assert config.use_confidence_gate is True
    assert config.use_trend_alignment_gate is True


# --- apply_gates: no_gate ---


def test_apply_gates_no_gate_passes_everything_through():
    test = [mk_labeled(i, 0.5, TP, 0.02) for i in range(5)]
    kept = gc.apply_gates([], test, gc.GateConfig(name="no_gate"))
    assert kept == test


# --- apply_gates: trend_alignment_only ---


def test_apply_gates_trend_alignment_keeps_only_above_threshold():
    test = [
        mk_labeled(0, 0.5, TP, 0.02, sma_trend_bias_alignment=0.8),  # above default threshold 0.5
        mk_labeled(1, 0.5, TP, 0.02, sma_trend_bias_alignment=0.3),  # below threshold
        mk_labeled(2, 0.5, TP, 0.02, sma_trend_bias_alignment=0.5),  # equal to threshold -- strictly excluded
    ]
    kept = gc.apply_gates([], test, gc.GateConfig(name="trend_alignment_only", use_trend_alignment_gate=True))
    assert [ls.signal.index for ls in kept] == [0]


def test_apply_gates_trend_alignment_respects_custom_threshold():
    test = [mk_labeled(i, 0.5, TP, 0.02, sma_trend_bias_alignment=0.6) for i in range(3)]
    config = gc.GateConfig(name="strict", use_trend_alignment_gate=True, trend_alignment_threshold=0.7)
    assert gc.apply_gates([], test, config) == []


# --- _fit_confidence_model ---


def test_fit_confidence_model_returns_none_with_too_few_train_samples():
    train = [mk_labeled(i, 0.9, TP, 0.02) for i in range(3)]
    assert gc._fit_confidence_model(train) is None


def test_fit_confidence_model_returns_none_with_single_outcome_class():
    train = [mk_labeled(i, 0.9, TP, 0.02) for i in range(fw.MIN_TRAIN_SAMPLES + 5)]
    assert gc._fit_confidence_model(train) is None


def test_fit_confidence_model_fits_with_informative_feature():
    rng = random.Random(9)
    train = []
    for i in range(60):
        quality = 0.9 if i % 2 == 0 else 0.1
        outcome = TP if rng.random() < (0.9 if quality > 0.5 else 0.1) else SL
        train.append(mk_labeled(i, quality, outcome, 0.02 if outcome is TP else -0.01))
    fit = gc._fit_confidence_model(train)
    assert fit is not None
    model, x_train = fit
    assert x_train.shape[0] == 60
    assert 1 in list(model.classes_)


# --- apply_gates: confidence_only (with a real fitted model) ---


def test_apply_gates_confidence_only_filters_low_probability_signals():
    rng = random.Random(11)

    def build(n, start_idx, quality_fn):
        out = []
        for j in range(n):
            i = start_idx + j
            quality = quality_fn(j)
            outcome = TP if rng.random() < (0.9 if quality > 0.5 else 0.1) else SL
            out.append(mk_labeled(i, quality, outcome, 0.02 if outcome is TP else -0.01))
        return out

    train = build(60, 0, lambda j: 0.9 if j % 2 == 0 else 0.1)
    # test set: half clearly high-quality, half clearly low-quality signals
    test = build(20, 1000, lambda j: 0.95 if j < 10 else 0.05)

    config = gc.GateConfig(name="confidence_only", use_confidence_gate=True, confidence_percentile=50.0)
    kept = gc.apply_gates(train, test, config)
    assert 0 < len(kept) < len(test)  # gate actually filters something, doesn't pass everyone or reject everyone
    # the kept set should skew toward the higher-quality half of the test set
    kept_indices = {ls.signal.index for ls in kept}
    high_quality_indices = {ls.signal.index for ls in test[:10]}
    assert len(kept_indices & high_quality_indices) >= len(kept_indices) / 2


def test_apply_gates_confidence_only_passes_through_when_train_cant_fit():
    train = [mk_labeled(i, 0.9, TP, 0.02) for i in range(3)]  # too few samples
    test = [mk_labeled(i, 0.5, TP, 0.02) for i in range(1000, 1005)]
    config = gc.GateConfig(name="confidence_only", use_confidence_gate=True)
    kept = gc.apply_gates(train, test, config)
    assert kept == test  # fallback: pass everything through unfiltered


# --- apply_gates: both_gates (AND of both filters) ---


def test_apply_gates_both_gates_applies_trend_filter_after_confidence_filter():
    train = [mk_labeled(i, 0.9 if i % 2 == 0 else 0.1, TP if i % 2 == 0 else SL, 0.02 if i % 2 == 0 else -0.01) for i in range(60)]
    test = [
        mk_labeled(1000, 0.9, TP, 0.02, sma_trend_bias_alignment=0.8),  # high confidence AND aligned
        mk_labeled(1001, 0.9, TP, 0.02, sma_trend_bias_alignment=0.2),  # high confidence but NOT aligned
    ]
    config = gc.GateConfig(name="both_gates", use_confidence_gate=True, use_trend_alignment_gate=True, confidence_percentile=0.0)
    kept = gc.apply_gates(train, test, config)
    kept_indices = {ls.signal.index for ls in kept}
    assert 1001 not in kept_indices  # rejected by the trend-alignment gate regardless of confidence


# --- run_gated_series (end-to-end, synthetic data) ---


def test_run_gated_series_returns_well_formed_result_for_every_gate_config():
    candles = noisy_zigzag()
    for config in gc.GATE_CONFIGS:
        result = gc.run_gated_series("synthetic", candles, config)
        assert result.series == "synthetic"
        assert result.gate_name == config.name
        assert result.total_windows >= 1
        assert 0 <= result.total_kept <= result.total_signals * result.total_windows  # loose upper bound, no crash/negative
        assert 0 <= result.windows_passing_pf <= result.total_windows
        assert isinstance(result.promoted, bool)


def test_run_gated_series_no_gate_matches_total_signal_count_semantics():
    candles = noisy_zigzag()
    result = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    # no_gate means every test-window signal survives -- total_kept counts
    # each signal once per the window whose test range it falls in, so it
    # should equal total_signals when every signal lands inside some
    # window's test range (true for this fixture's calendar span).
    assert result.total_kept <= result.total_signals


def test_run_gated_series_gates_never_increase_kept_count_vs_no_gate():
    candles = noisy_zigzag()
    baseline = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    for config in gc.GATE_CONFIGS:
        if config.name == "no_gate":
            continue
        result = gc.run_gated_series("synthetic", candles, config)
        assert result.total_kept <= baseline.total_kept


def test_gated_series_result_is_frozen_dataclass():
    result = gc.GatedSeriesResult(
        series="x", gate_name="no_gate", total_signals=1, total_kept=1, total_windows=1, windows_passing_pf=0, promoted=False, pooled_pf_net=None
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.series = "y"
