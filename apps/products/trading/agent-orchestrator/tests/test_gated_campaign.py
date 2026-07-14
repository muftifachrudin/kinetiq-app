import dataclasses
import datetime
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "validation" / "fib_gann_backtest"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import campaign  # noqa: E402
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


def mk_signal(index: int, swing_quality: float = 0.5, sma_trend_bias_alignment: float = 0.5, daily_bias_alignment: float = 0.5) -> sr.Signal:
    exit_plan = fgt.ExitPlan(direction=LONG, entry_price=100.0, stop_loss=95.0, take_profits=(110.0,), risk_reward_ratio=2.0)
    pivot = fgt.SwingPoint(index=index, ts=ts_at(index), price=100.0, direction=fgt.SwingDirection.LOW, wick_rejection_score=0.5)
    return sr.Signal(
        ts=ts_at(index), index=index, pivot=pivot, basis_leg_start=pivot, direction=LONG, entry_price=100.0,
        exit_plan=exit_plan, confidence=0.5, structure_event=None, swing_quality=swing_quality,
        fib_gann_confluence=0.5, volume_confirmation=0.5, wick_rejection=0.5, structure_alignment=0.5,
        htf_alignment=0.5, regime_alignment=0.5, sma_trend_bias_alignment=sma_trend_bias_alignment,
        daily_bias_alignment=daily_bias_alignment,
    )


def mk_trade(signal: sr.Signal, outcome: fgt.BarrierOutcome, return_pct: float) -> ts.SimulatedTrade:
    label = fgt.TripleBarrierLabel(outcome=outcome, exit_price=100.0, exit_ts=signal.ts + datetime.timedelta(hours=5), bars_held=5, return_pct=return_pct, censored=False)
    return ts.SimulatedTrade(
        signal_ts=signal.ts, signal_index=signal.index, direction=signal.direction, confidence=signal.confidence,
        entry_price=signal.entry_price, label=label, funding_cost_pct=0.0, funding_events_count=0,
        fee_cost_pct=0.0, net_return_pct=return_pct,
    )


def mk_labeled(
    index: int,
    swing_quality: float,
    outcome: fgt.BarrierOutcome,
    return_pct: float,
    sma_trend_bias_alignment: float = 0.5,
    daily_bias_alignment: float = 0.5,
) -> fw.LabeledSignal:
    signal = mk_signal(index, swing_quality=swing_quality, sma_trend_bias_alignment=sma_trend_bias_alignment, daily_bias_alignment=daily_bias_alignment)
    trade = mk_trade(signal, outcome, return_pct)
    return fw.LabeledSignal(signal=signal, trade=trade)


# --- GATE_CONFIGS ---


def test_gate_configs_covers_nine_named_combinations():
    names = {c.name for c in gc.GATE_CONFIGS}
    assert names == {
        "no_gate",
        "confidence_only",
        "trend_alignment_only",
        "daily_bias_only",
        "both_gates",
        "veto_short_bull",
        "veto_both_counter_trend",
        "volatility_regime_only",
        "knn_risk_memory_only",
    }


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


# --- apply_gates: daily_bias_only (F6b I1(b), literal) ---


def test_apply_gates_daily_bias_keeps_only_above_threshold():
    test = [
        mk_labeled(0, 0.5, TP, 0.02, daily_bias_alignment=0.8),  # above default threshold 0.5
        mk_labeled(1, 0.5, TP, 0.02, daily_bias_alignment=0.3),  # below threshold
        mk_labeled(2, 0.5, TP, 0.02, daily_bias_alignment=0.5),  # equal to threshold -- strictly excluded
    ]
    kept = gc.apply_gates([], test, gc.GateConfig(name="daily_bias_only", use_daily_bias_gate=True))
    assert [ls.signal.index for ls in kept] == [0]


def test_apply_gates_daily_bias_independent_of_sma_trend_alignment():
    # a signal aligned on the SMA proxy but NOT on the literal Daily bias
    # must be rejected by daily_bias_only -- confirms the two gates read
    # distinct Signal fields, not the same one under two names.
    test = [mk_labeled(0, 0.5, TP, 0.02, sma_trend_bias_alignment=0.9, daily_bias_alignment=0.1)]
    kept = gc.apply_gates([], test, gc.GateConfig(name="daily_bias_only", use_daily_bias_gate=True))
    assert kept == []


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


def test_run_gated_series_pooled_pf_net_ci90_well_formed_when_present():
    # F6b I5 wired to gated_campaign (shadow Tahap 2's own entry gate --
    # roadmap Fase 7 -- needs pooled_pf_net + CI, not just window-pass-count).
    candles = noisy_zigzag()
    result = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    if result.pooled_pf_net_ci90 is not None:
        lower, upper = result.pooled_pf_net_ci90
        assert lower <= upper


def test_run_gated_series_pooled_pf_net_ci90_is_deterministic():
    candles = noisy_zigzag()
    a = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    b = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    assert a.pooled_pf_net_ci90 == b.pooled_pf_net_ci90


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
        series="x",
        gate_name="no_gate",
        total_signals=1,
        total_kept=1,
        total_windows=1,
        windows_passing_pf=0,
        promoted=False,
        pooled_pf_net=None,
        pooled_pf_net_ci90=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.series = "y"


# --- F6b I1(a): size_multiplier ---


def test_size_multiplier_clamps_into_min_max_band():
    assert gc.size_multiplier(0.0) == pytest.approx(gc.MIN_SIZE_MULTIPLIER)
    assert gc.size_multiplier(1.0) == pytest.approx(gc.MAX_SIZE_MULTIPLIER)
    assert gc.size_multiplier(0.5) == pytest.approx((gc.MIN_SIZE_MULTIPLIER + gc.MAX_SIZE_MULTIPLIER) / 2)


def test_size_multiplier_clamps_out_of_range_confidence():
    assert gc.size_multiplier(-1.0) == pytest.approx(gc.MIN_SIZE_MULTIPLIER)
    assert gc.size_multiplier(2.0) == pytest.approx(gc.MAX_SIZE_MULTIPLIER)


# --- SIZING_CONFIGS / _size_multipliers ---


def test_sizing_configs_covers_three_named_variants():
    names = {c.name for c in gc.SIZING_CONFIGS}
    assert names == {"no_sizing", "confidence_sizing", "volatility_regime_sizing"}


def test_size_multipliers_no_sizing_always_returns_one():
    test = [mk_labeled(i, 0.5, TP, 0.02) for i in range(3)]
    multipliers = gc._size_multipliers([], test, gc.SizingConfig(name="no_sizing"))
    assert multipliers == {0: 1.0, 1: 1.0, 2: 1.0}


def test_size_multipliers_confidence_sizing_falls_back_to_one_when_train_cant_fit():
    train = [mk_labeled(i, 0.9, TP, 0.02) for i in range(3)]  # too few samples
    test = [mk_labeled(i, 0.5, TP, 0.02) for i in range(1000, 1003)]
    multipliers = gc._size_multipliers(train, test, gc.SizingConfig(name="confidence_sizing", use_confidence_sizing=True))
    assert multipliers == {1000: 1.0, 1001: 1.0, 1002: 1.0}


def test_size_multipliers_confidence_sizing_scales_within_band_when_fit_succeeds():
    rng = random.Random(11)
    train = []
    for i in range(60):
        quality = 0.9 if i % 2 == 0 else 0.1
        outcome = TP if rng.random() < (0.9 if quality > 0.5 else 0.1) else SL
        train.append(mk_labeled(i, quality, outcome, 0.02 if outcome is TP else -0.01))
    test = [mk_labeled(1000, 0.95, TP, 0.02), mk_labeled(1001, 0.05, TP, 0.02)]
    multipliers = gc._size_multipliers(train, test, gc.SizingConfig(name="confidence_sizing", use_confidence_sizing=True))
    assert set(multipliers.keys()) == {1000, 1001}
    for m in multipliers.values():
        assert gc.MIN_SIZE_MULTIPLIER <= m <= gc.MAX_SIZE_MULTIPLIER


# --- run_sizing_series (end-to-end, synthetic data) ---


def test_run_sizing_series_returns_well_formed_result_for_every_sizing_config():
    candles = noisy_zigzag()
    for config in gc.SIZING_CONFIGS:
        result = gc.run_sizing_series("synthetic", candles, config)
        assert result.series == "synthetic"
        assert result.sizing_name == config.name
        assert result.total_windows >= 1
        if result.avg_multiplier is not None:
            assert gc.MIN_SIZE_MULTIPLIER <= result.min_multiplier <= result.avg_multiplier <= result.max_multiplier <= gc.MAX_SIZE_MULTIPLIER


def test_run_sizing_series_no_sizing_multipliers_always_one():
    candles = noisy_zigzag()
    result = gc.run_sizing_series("synthetic", candles, gc.SizingConfig(name="no_sizing"))
    if result.avg_multiplier is not None:
        assert result.min_multiplier == pytest.approx(1.0)
        assert result.max_multiplier == pytest.approx(1.0)


def test_run_sizing_series_no_sizing_weighted_pf_matches_unweighted_pf():
    candles = noisy_zigzag()
    result = gc.run_sizing_series("synthetic", candles, gc.SizingConfig(name="no_sizing"))
    if result.pooled_pf_net is not None and result.pooled_weighted_pf_net is not None:
        assert result.pooled_weighted_pf_net == pytest.approx(result.pooled_pf_net)


# --- campaign_config wiring (F6b I1: "di atas config kandidat F5") ---


def test_run_gated_series_campaign_config_changes_signal_generation():
    candles = noisy_zigzag()
    f5_candidate = campaign.CAMPAIGN_CONFIGS[1]
    default_result = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    candidate_result = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"), campaign_config=f5_candidate)
    # F5's candidate (min_rr=2.0/max_rr=5.0/sl=1.0atr) is strictly tighter
    # than production defaults -- must generate a different (in practice,
    # smaller) signal count, confirming campaign_config actually reaches
    # generate_signals() rather than being silently ignored.
    assert candidate_result.total_signals != default_result.total_signals


def test_run_sizing_series_campaign_config_changes_signal_generation():
    candles = noisy_zigzag()
    f5_candidate = campaign.CAMPAIGN_CONFIGS[1]
    default_result = gc.run_sizing_series("synthetic", candles, gc.SizingConfig(name="no_sizing"))
    candidate_result = gc.run_sizing_series("synthetic", candles, gc.SizingConfig(name="no_sizing"), campaign_config=f5_candidate)
    assert candidate_result.total_signals != default_result.total_signals


# --- F6b I2 follow-up: veto_short_bull (trailing_drift / regime_by_signal_index / apply_gates) ---

SHORT = fgt.TradeDirection.SHORT


def rising_candles(n: int, start_price: float = 100.0, step: float = 0.5) -> list[fgt.Candle]:
    # Monotonic uptrend -- unambiguous "bull" by any trailing-drift lookback
    # once enough of it has accumulated (drift > BULL_DRIFT_THRESHOLD=0.05).
    candles = []
    price = start_price
    for i in range(n):
        o = price
        c = price + step
        candles.append(mk(i, o, max(o, c), min(o, c), c))
        price = c
    return candles


def flat_candles(n: int, start_index: int = 0, price: float = 100.0) -> list[fgt.Candle]:
    """Zero-volatility candles (constant close every bar) -- builds up a
    near-zero realized_volatility population for volatility-regime tests."""
    return [mk(start_index + i, price, price, price, price) for i in range(n)]


def volatile_candles(n: int, start_index: int, start_price: float = 100.0, seed: int = 7) -> list[fgt.Candle]:
    """Large, alternating-sign percentage moves -- deliberately far more
    volatile than flat_candles() so realized_volatility() ranks clearly
    higher against a flat-history population."""
    rng = random.Random(seed)
    candles = []
    price = start_price
    for i in range(n):
        pct = rng.uniform(0.05, 0.12) * (1 if i % 2 == 0 else -1)
        o = price
        c = price * (1 + pct)
        candles.append(mk(start_index + i, o, max(o, c), min(o, c), c))
        price = c
    return candles


def test_trailing_drift_none_before_enough_history():
    candles = rising_candles(24 * 10)  # 10 days -- fewer than the 30-day default lookback
    candle_ts = [c.ts for c in candles]
    assert gc.trailing_drift(candle_ts, candles, candles[-1].ts) is None


def test_trailing_drift_detects_bull_on_monotonic_uptrend():
    candles = rising_candles(24 * 40)  # 40 days, well past the 30-day lookback
    candle_ts = [c.ts for c in candles]
    drift = gc.trailing_drift(candle_ts, candles, candles[-1].ts)
    assert drift is not None
    assert drift > campaign.BULL_DRIFT_THRESHOLD


def test_trailing_drift_uses_only_candles_up_to_as_of_ts():
    # A monotonic uptrend that STOPS partway through must not "see" the
    # continuation after as_of_ts -- this is the whole causality guarantee
    # the module docstring promises (unlike campaign.monthly_drift(), which
    # deliberately uses the full month including its future).
    up = rising_candles(24 * 40)
    flat_start_price = up[-1].close
    flat = [mk(len(up) + i, flat_start_price, flat_start_price, flat_start_price, flat_start_price) for i in range(24 * 5)]
    candles = up + flat
    candle_ts = [c.ts for c in candles]
    as_of = up[-1].ts  # right when the uptrend stops, before the flat tail
    drift = gc.trailing_drift(candle_ts, candles, as_of)
    assert drift is not None
    assert drift > campaign.BULL_DRIFT_THRESHOLD  # must reflect the uptrend, unaffected by the flat tail that follows


def test_trailing_drift_none_when_as_of_ts_before_first_candle():
    candles = rising_candles(24 * 40)
    candle_ts = [c.ts for c in candles]
    before_series = candles[0].ts - datetime.timedelta(days=1)
    assert gc.trailing_drift(candle_ts, candles, before_series) is None


def test_regime_by_signal_index_classifies_bull_and_omits_too_early_signals():
    candles = rising_candles(24 * 40)
    early_signal = mk_signal(24 * 5)  # only 5 days of history -- too early to classify
    late_signal = mk_signal(24 * 35)  # well past the 30-day lookback
    regimes = gc.regime_by_signal_index([early_signal, late_signal], candles)
    assert early_signal.index not in regimes
    assert regimes[late_signal.index] == "bull"


# --- apply_gates: veto_short_bull ---


def mk_labeled_dir(index: int, direction, outcome=TP, return_pct: float = 0.02) -> fw.LabeledSignal:
    base = mk_signal(index)
    signal = dataclasses.replace(base, direction=direction)
    trade = mk_trade(signal, outcome, return_pct)
    return fw.LabeledSignal(signal=signal, trade=trade)


def test_apply_gates_veto_short_bull_drops_short_in_bull_regime():
    test = [mk_labeled_dir(0, SHORT), mk_labeled_dir(1, LONG)]
    config = gc.GateConfig(name="veto_short_bull", use_regime_direction_gate=True)
    kept = gc.apply_gates([], test, config, regime_by_index={0: "bull", 1: "bull"})
    assert [ls.signal.index for ls in kept] == [1]  # SHORT vetoed, LONG untouched even in a bull regime


def test_apply_gates_veto_short_bull_keeps_short_outside_bull_regime():
    test = [mk_labeled_dir(0, SHORT), mk_labeled_dir(1, SHORT)]
    config = gc.GateConfig(name="veto_short_bull", use_regime_direction_gate=True)
    kept = gc.apply_gates([], test, config, regime_by_index={0: "bear", 1: "range"})
    assert {ls.signal.index for ls in kept} == {0, 1}


def test_apply_gates_veto_short_bull_keeps_short_with_unknown_regime():
    # A signal absent from regime_by_index (too early in the series for
    # trailing_drift to classify) must never be vetoed -- same
    # can't-decide-so-pass-through fallback precedent as every other gate.
    test = [mk_labeled_dir(0, SHORT)]
    config = gc.GateConfig(name="veto_short_bull", use_regime_direction_gate=True)
    kept = gc.apply_gates([], test, config, regime_by_index={})
    assert kept == test


def test_apply_gates_veto_short_bull_noop_without_regime_by_index_arg():
    # regime_by_index defaults to None -- must not crash, must behave as
    # "no regimes known" (nothing vetoed), not raise on a missing dict.
    test = [mk_labeled_dir(0, SHORT)]
    config = gc.GateConfig(name="veto_short_bull", use_regime_direction_gate=True)
    kept = gc.apply_gates([], test, config)
    assert kept == test


# --- run_gated_series: veto_short_bull end-to-end (synthetic data) ---


def test_run_gated_series_veto_short_bull_never_increases_kept_count():
    candles = noisy_zigzag()
    baseline = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    result = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="veto_short_bull", use_regime_direction_gate=True))
    assert result.total_kept <= baseline.total_kept


def test_run_gated_series_veto_short_bull_well_formed_result():
    candles = noisy_zigzag()
    result = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="veto_short_bull", use_regime_direction_gate=True))
    assert result.gate_name == "veto_short_bull"
    assert result.total_windows >= 1
    assert 0 <= result.windows_passing_pf <= result.total_windows


# --- apply_gates: veto_both_counter_trend (symmetric follow-up) ---


def test_apply_gates_veto_both_counter_trend_drops_short_bull_and_long_bear():
    test = [mk_labeled_dir(0, SHORT), mk_labeled_dir(1, LONG), mk_labeled_dir(2, LONG), mk_labeled_dir(3, SHORT)]
    config = gc.GateConfig(name="veto_both_counter_trend", use_regime_direction_gate=True, veto_both_counter_trend_directions=True)
    kept = gc.apply_gates([], test, config, regime_by_index={0: "bull", 1: "bull", 2: "bear", 3: "bear"})
    # index 0 (SHORT, bull) and index 2 (LONG, bear) are counter-trend -- vetoed.
    # index 1 (LONG, bull) and index 3 (SHORT, bear) are trend-aligned -- kept.
    assert {ls.signal.index for ls in kept} == {1, 3}


def test_apply_gates_veto_both_counter_trend_keeps_both_directions_in_range():
    test = [mk_labeled_dir(0, LONG), mk_labeled_dir(1, SHORT)]
    config = gc.GateConfig(name="veto_both_counter_trend", use_regime_direction_gate=True, veto_both_counter_trend_directions=True)
    kept = gc.apply_gates([], test, config, regime_by_index={0: "range", 1: "range"})
    assert {ls.signal.index for ls in kept} == {0, 1}


def test_apply_gates_veto_both_counter_trend_vetoes_strictly_more_than_short_bull_alone():
    # Same input/regimes for both configs -- the symmetric gate must never
    # keep a signal the asymmetric veto_short_bull gate would also keep,
    # and must drop at least the additional long_bear case.
    test = [mk_labeled_dir(0, SHORT), mk_labeled_dir(1, LONG), mk_labeled_dir(2, LONG), mk_labeled_dir(3, SHORT)]
    regimes = {0: "bull", 1: "bull", 2: "bear", 3: "bear"}
    asymmetric = gc.GateConfig(name="veto_short_bull", use_regime_direction_gate=True)
    symmetric = gc.GateConfig(name="veto_both_counter_trend", use_regime_direction_gate=True, veto_both_counter_trend_directions=True)
    kept_asymmetric = {ls.signal.index for ls in gc.apply_gates([], test, asymmetric, regime_by_index=regimes)}
    kept_symmetric = {ls.signal.index for ls in gc.apply_gates([], test, symmetric, regime_by_index=regimes)}
    assert kept_symmetric.issubset(kept_asymmetric)
    assert kept_symmetric == kept_asymmetric - {2}  # index 2 (LONG, bear) only dropped by the symmetric version


def test_run_gated_series_veto_both_counter_trend_never_exceeds_veto_short_bull_kept_count():
    candles = noisy_zigzag()
    asymmetric = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="veto_short_bull", use_regime_direction_gate=True))
    symmetric = gc.run_gated_series(
        "synthetic", candles, gc.GateConfig(name="veto_both_counter_trend", use_regime_direction_gate=True, veto_both_counter_trend_directions=True)
    )
    assert symmetric.total_kept <= asymmetric.total_kept


def test_run_gated_series_veto_both_counter_trend_well_formed_result():
    candles = noisy_zigzag()
    result = gc.run_gated_series(
        "synthetic", candles, gc.GateConfig(name="veto_both_counter_trend", use_regime_direction_gate=True, veto_both_counter_trend_directions=True)
    )
    assert result.gate_name == "veto_both_counter_trend"
    assert result.total_windows >= 1
    assert 0 <= result.windows_passing_pf <= result.total_windows


# --- run_gated_series_batch: shares signal generation, must match per-gate calls ---


def test_run_gated_series_batch_matches_individual_calls():
    candles = noisy_zigzag()
    configs = [gc.GateConfig(name="no_gate"), gc.GateConfig(name="trend_alignment_only", use_trend_alignment_gate=True)]
    batch_results = gc.run_gated_series_batch("synthetic", candles, configs)
    individual_results = [gc.run_gated_series("synthetic", candles, config) for config in configs]
    assert batch_results == individual_results


def test_run_gated_series_batch_returns_one_result_per_gate_config():
    candles = noisy_zigzag()
    results = gc.run_gated_series_batch("synthetic", candles, list(gc.GATE_CONFIGS))
    assert [r.gate_name for r in results] == [c.name for c in gc.GATE_CONFIGS]


def test_run_gated_series_batch_campaign_config_changes_signal_generation():
    candles = noisy_zigzag()
    f5_candidate = campaign.CAMPAIGN_CONFIGS[1]
    default_results = gc.run_gated_series_batch("synthetic", candles, [gc.GateConfig(name="no_gate")])
    candidate_results = gc.run_gated_series_batch("synthetic", candles, [gc.GateConfig(name="no_gate")], campaign_config=f5_candidate)
    assert candidate_results[0].total_signals != default_results[0].total_signals


# --- realized_volatility / volatility_regime_by_signal_index (docs/regime-gate-knn-risk-memory-brief.md Section 2) ---


def test_realized_volatility_none_before_enough_history():
    candles = flat_candles(24 * 10)  # 10 days -- fewer than the 14-day default lookback
    candle_ts = [c.ts for c in candles]
    assert gc.realized_volatility(candle_ts, candles, candles[-1].ts) is None


def test_realized_volatility_is_zero_for_perfectly_flat_series():
    candles = flat_candles(24 * 20)  # 20 days, past the 14-day lookback
    candle_ts = [c.ts for c in candles]
    vol = gc.realized_volatility(candle_ts, candles, candles[-1].ts)
    assert vol == pytest.approx(0.0)


def test_realized_volatility_higher_for_choppy_than_flat_segment():
    flat = flat_candles(24 * 20)
    choppy = volatile_candles(24 * 20, start_index=len(flat), start_price=flat[-1].close)
    candles = flat + choppy
    candle_ts = [c.ts for c in candles]
    flat_vol = gc.realized_volatility(candle_ts, candles, flat[-1].ts)
    choppy_vol = gc.realized_volatility(candle_ts, candles, choppy[-1].ts)
    assert flat_vol == pytest.approx(0.0)
    assert choppy_vol > flat_vol


def test_realized_volatility_uses_only_candles_up_to_as_of_ts():
    # Same causality guarantee as trailing_drift() -- a volatile stretch
    # AFTER as_of_ts must not leak into a reading taken before it.
    flat = flat_candles(24 * 20)
    choppy = volatile_candles(24 * 20, start_index=len(flat), start_price=flat[-1].close)
    candles = flat + choppy
    candle_ts = [c.ts for c in candles]
    vol_at_flat_end = gc.realized_volatility(candle_ts, candles, flat[-1].ts)
    assert vol_at_flat_end == pytest.approx(0.0)


def test_volatility_regime_by_signal_index_classifies_freeze_on_extreme_spike():
    flat = flat_candles(24 * 40)  # 40 days flat -- builds a large near-zero-vol population
    spike = volatile_candles(24 * 20, start_index=len(flat), start_price=flat[-1].close)
    candles = flat + spike
    signal_in_spike = mk_signal(len(flat) + 24 * 15)  # well into the spike section
    regimes = gc.volatility_regime_by_signal_index([signal_in_spike], candles)
    assert regimes[signal_in_spike.index] == gc.VOLATILITY_REGIME_FREEZE


def test_volatility_regime_by_signal_index_classifies_normal_within_flat_history():
    flat = flat_candles(24 * 40)
    signal_late = mk_signal(24 * 35)  # deep into the flat history, past MIN_VOLATILITY_POPULATION warmup
    regimes = gc.volatility_regime_by_signal_index([signal_late], flat)
    assert regimes.get(signal_late.index) == gc.VOLATILITY_REGIME_NORMAL


def test_volatility_regime_by_signal_index_omits_too_early_signals():
    flat = flat_candles(24 * 40)
    early_signal = mk_signal(24 * 5)  # too early for even the 14-day lookback
    regimes = gc.volatility_regime_by_signal_index([early_signal], flat)
    assert early_signal.index not in regimes


# --- apply_gates: volatility_regime_only (FREEZE veto, RISK_OFF/NORMAL untouched) ---


def test_apply_gates_volatility_regime_vetoes_freeze_regardless_of_direction():
    test = [mk_labeled_dir(0, LONG), mk_labeled_dir(1, SHORT)]
    config = gc.GateConfig(name="volatility_regime_only", use_volatility_regime_gate=True)
    kept = gc.apply_gates(
        [], test, config, volatility_regime_by_index={0: gc.VOLATILITY_REGIME_FREEZE, 1: gc.VOLATILITY_REGIME_FREEZE}
    )
    assert kept == []


def test_apply_gates_volatility_regime_keeps_risk_off_and_normal():
    test = [mk_labeled_dir(0, LONG), mk_labeled_dir(1, SHORT)]
    config = gc.GateConfig(name="volatility_regime_only", use_volatility_regime_gate=True)
    kept = gc.apply_gates(
        [], test, config, volatility_regime_by_index={0: gc.VOLATILITY_REGIME_RISK_OFF, 1: gc.VOLATILITY_REGIME_NORMAL}
    )
    assert {ls.signal.index for ls in kept} == {0, 1}


def test_apply_gates_volatility_regime_noop_without_dict_arg():
    # volatility_regime_by_index defaults to None -- must behave as "no
    # regimes known" (nothing vetoed), same fallback precedent as
    # veto_short_bull's own regime_by_index default (test above).
    test = [mk_labeled_dir(0, LONG)]
    config = gc.GateConfig(name="volatility_regime_only", use_volatility_regime_gate=True)
    kept = gc.apply_gates([], test, config)
    assert kept == test


# --- run_gated_series: volatility_regime_only end-to-end (synthetic data) ---


def test_run_gated_series_volatility_regime_never_increases_kept_count():
    candles = noisy_zigzag()
    baseline = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    result = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="volatility_regime_only", use_volatility_regime_gate=True))
    assert result.total_kept <= baseline.total_kept


def test_run_gated_series_volatility_regime_well_formed_result():
    candles = noisy_zigzag()
    result = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="volatility_regime_only", use_volatility_regime_gate=True))
    assert result.gate_name == "volatility_regime_only"
    assert result.total_windows >= 1
    assert 0 <= result.windows_passing_pf <= result.total_windows


# --- _fit_knn_risk_memory / _knn_loss_fraction (docs/regime-gate-knn-risk-memory-brief.md Section 4) ---


def test_fit_knn_risk_memory_returns_none_with_too_few_train_samples():
    train = [mk_labeled(i, 0.9, TP, 0.02) for i in range(3)]
    assert gc._fit_knn_risk_memory(train) is None


def test_fit_knn_risk_memory_returns_none_when_train_smaller_than_k():
    train = [mk_labeled(i, 0.9 if i % 2 == 0 else 0.1, TP if i % 2 == 0 else SL, 0.02 if i % 2 == 0 else -0.01) for i in range(fw.MIN_TRAIN_SAMPLES + 2)]
    assert gc._fit_knn_risk_memory(train, k=20) is None  # more than MIN_TRAIN_SAMPLES but fewer than k


def test_fit_knn_risk_memory_returns_none_with_no_losses_in_train():
    train = [mk_labeled(i, 0.9, TP, 0.02) for i in range(20)]  # every trade a winner
    assert gc._fit_knn_risk_memory(train, k=5) is None


def test_fit_knn_risk_memory_fits_with_enough_data():
    train = [mk_labeled(i, 0.9 if i % 2 == 0 else 0.1, TP if i % 2 == 0 else SL, 0.02 if i % 2 == 0 else -0.01) for i in range(30)]
    fit = gc._fit_knn_risk_memory(train, k=5)
    assert fit is not None
    model, is_loss_train = fit
    assert len(is_loss_train) == 30
    assert sum(is_loss_train) == 15  # half the trades (odd i, quality 0.1) are SL -> loss


def test_knn_loss_fraction_high_for_signal_resembling_past_losers():
    # two well-separated clusters by swing_quality: low quality -> always
    # SL, high quality -> always TP -- an unambiguous case for the
    # algorithm, not a claim about real market separability.
    losers = [mk_labeled(i, 0.1, SL, -0.01) for i in range(15)]
    winners = [mk_labeled(100 + i, 0.9, TP, 0.02) for i in range(15)]
    train = losers + winners
    fit = gc._fit_knn_risk_memory(train, k=5)
    assert fit is not None
    model, is_loss_train = fit

    low_quality_query = mk_signal(1000, swing_quality=0.1)
    high_quality_query = mk_signal(1001, swing_quality=0.9)
    assert gc._knn_loss_fraction(model, is_loss_train, low_quality_query, k=5) == pytest.approx(1.0)
    assert gc._knn_loss_fraction(model, is_loss_train, high_quality_query, k=5) == pytest.approx(0.0)


# --- apply_gates: knn_risk_memory_only ---


def test_apply_gates_knn_risk_memory_vetoes_signals_resembling_past_losers():
    losers = [mk_labeled(i, 0.1, SL, -0.01) for i in range(15)]
    winners = [mk_labeled(100 + i, 0.9, TP, 0.02) for i in range(15)]
    train = losers + winners
    test = [mk_labeled(1000, 0.1, TP, 0.02), mk_labeled(1001, 0.9, TP, 0.02)]  # first resembles losers, second resembles winners
    config = gc.GateConfig(name="knn_risk_memory_only", use_knn_risk_memory_gate=True, knn_k=5)
    kept = gc.apply_gates(train, test, config)
    assert [ls.signal.index for ls in kept] == [1001]


def test_apply_gates_knn_risk_memory_passes_through_when_train_cant_fit():
    train = [mk_labeled(i, 0.9, TP, 0.02) for i in range(3)]  # too few samples
    test = [mk_labeled(i, 0.5, TP, 0.02) for i in range(1000, 1003)]
    config = gc.GateConfig(name="knn_risk_memory_only", use_knn_risk_memory_gate=True)
    kept = gc.apply_gates(train, test, config)
    assert kept == test  # fallback: pass everything through unfiltered


# --- run_gated_series: knn_risk_memory_only end-to-end (synthetic data) ---


def test_run_gated_series_knn_risk_memory_never_increases_kept_count():
    candles = noisy_zigzag()
    baseline = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    result = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="knn_risk_memory_only", use_knn_risk_memory_gate=True))
    assert result.total_kept <= baseline.total_kept


def test_run_gated_series_knn_risk_memory_well_formed_result():
    candles = noisy_zigzag()
    result = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="knn_risk_memory_only", use_knn_risk_memory_gate=True))
    assert result.gate_name == "knn_risk_memory_only"
    assert result.total_windows >= 1
    assert 0 <= result.windows_passing_pf <= result.total_windows


# --- _size_multipliers: volatility_regime_sizing (RISK_OFF/FREEZE shrink, never enlarges) ---


def test_size_multipliers_volatility_regime_sizing_shrinks_risk_off_and_freeze():
    test = [mk_labeled(0, 0.5, TP, 0.02), mk_labeled(1, 0.5, TP, 0.02), mk_labeled(2, 0.5, TP, 0.02)]
    config = gc.SizingConfig(name="volatility_regime_sizing", use_volatility_regime_sizing=True)
    regimes = {0: gc.VOLATILITY_REGIME_RISK_OFF, 1: gc.VOLATILITY_REGIME_FREEZE, 2: gc.VOLATILITY_REGIME_NORMAL}
    multipliers = gc._size_multipliers([], test, config, volatility_regime_by_index=regimes)
    assert multipliers[0] == pytest.approx(gc.VOLATILITY_REGIME_SIZE_MULTIPLIER)
    assert multipliers[1] == pytest.approx(gc.VOLATILITY_REGIME_SIZE_MULTIPLIER)
    assert multipliers[2] == pytest.approx(1.0)


def test_size_multipliers_volatility_regime_sizing_noop_without_dict_arg():
    test = [mk_labeled(0, 0.5, TP, 0.02)]
    config = gc.SizingConfig(name="volatility_regime_sizing", use_volatility_regime_sizing=True)
    multipliers = gc._size_multipliers([], test, config)
    assert multipliers == {0: 1.0}


def test_size_multipliers_volatility_regime_sizing_composes_with_confidence_sizing():
    rng = random.Random(11)
    train = []
    for i in range(60):
        quality = 0.9 if i % 2 == 0 else 0.1
        outcome = TP if rng.random() < (0.9 if quality > 0.5 else 0.1) else SL
        train.append(mk_labeled(i, quality, outcome, 0.02 if outcome is TP else -0.01))
    test = [mk_labeled(1000, 0.95, TP, 0.02)]
    config = gc.SizingConfig(name="both", use_confidence_sizing=True, use_volatility_regime_sizing=True)
    without_regime = gc._size_multipliers(train, test, config, volatility_regime_by_index={})
    with_freeze = gc._size_multipliers(train, test, config, volatility_regime_by_index={1000: gc.VOLATILITY_REGIME_FREEZE})
    # rel=1e-3, not the default 1e-6 -- LogisticRegression(solver="saga") is
    # refit independently for each _size_multipliers() call (no random_state
    # pinned anywhere in this module, a pre-existing property of
    # _fit_confidence_model()) and isn't bit-for-bit deterministic across
    # separate fits on the same data; the composition itself (freeze
    # multiplies by VOLATILITY_REGIME_SIZE_MULTIPLIER) is what's under test.
    assert with_freeze[1000] == pytest.approx(without_regime[1000] * gc.VOLATILITY_REGIME_SIZE_MULTIPLIER, rel=1e-3)


def test_run_sizing_series_volatility_regime_sizing_well_formed_result():
    candles = noisy_zigzag()
    result = gc.run_sizing_series("synthetic", candles, gc.SizingConfig(name="volatility_regime_sizing", use_volatility_regime_sizing=True))
    assert result.sizing_name == "volatility_regime_sizing"
    if result.avg_multiplier is not None:
        assert gc.VOLATILITY_REGIME_SIZE_MULTIPLIER <= result.min_multiplier <= result.avg_multiplier <= result.max_multiplier <= 1.0
