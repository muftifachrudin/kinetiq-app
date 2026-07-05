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
import market_structure as ms  # noqa: E402
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


def noisy_zigzag_15m(days: int = 70, seed: int = 43) -> list[fgt.Candle]:
    """15m companion series to noisy_zigzag() -- only veto_short_bull_ltf_
    override reads a separate 15m series alongside the entry-timeframe
    (1h) one, so every other gate's tests never need this fixture. Same
    "small, fast, synthetic, not real data" rationale as noisy_zigzag()
    itself, covering the same calendar span (`days`) so signals generated
    from noisy_zigzag() always have 15m history available."""
    rng = random.Random(seed)
    candles = []
    price = 100.0
    direction = -1
    n = days * 96  # 96 fifteen-minute candles/day
    start = datetime.datetime(2024, 1, 1, tzinfo=UTC)
    for i in range(n):
        if i % 60 == 0:
            direction *= -1
        price += direction * rng.uniform(0.05, 0.2)
        o = price
        c = price + rng.uniform(-0.05, 0.05)
        h = max(o, c) + rng.uniform(0, 0.05)
        low = min(o, c) - rng.uniform(0, 0.05)
        candles.append(fgt.Candle(ts=start + datetime.timedelta(minutes=15 * i), open=o, high=h, low=low, close=c, volume=100 + rng.uniform(-10, 10)))
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


def test_gate_configs_covers_eleven_named_combinations():
    names = {c.name for c in gc.GATE_CONFIGS}
    assert names == {
        "no_gate", "confidence_only", "trend_alignment_only", "daily_bias_only", "both_gates",
        "veto_short_bull", "veto_short_bull_ltf_override", "veto_long_bear", "veto_long_bear_ltf_override",
        "veto_short_bull_ltf_override_major_conflict", "veto_long_bear_ltf_override_major_conflict",
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
    candles_15m = noisy_zigzag_15m()
    for config in gc.GATE_CONFIGS:
        result = gc.run_gated_series("synthetic", candles, config, candles_15m=candles_15m)
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
    candles_15m = noisy_zigzag_15m()
    baseline = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    for config in gc.GATE_CONFIGS:
        if config.name == "no_gate":
            continue
        result = gc.run_gated_series("synthetic", candles, config, candles_15m=candles_15m)
        assert result.total_kept <= baseline.total_kept


def test_gated_series_result_is_frozen_dataclass():
    result = gc.GatedSeriesResult(
        series="x", gate_name="no_gate", total_signals=1, total_kept=1, total_windows=1, windows_passing_pf=0, promoted=False, pooled_pf_net=None
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


def test_sizing_configs_covers_two_named_variants():
    names = {c.name for c in gc.SIZING_CONFIGS}
    assert names == {"no_sizing", "confidence_sizing"}


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


# --- regime_by_signal_index: custom lookback_days/thresholds (F6b I2
# sensitivity follow-up) ---


def test_regime_by_signal_index_custom_lookback_days_changes_which_signals_classify():
    candles = rising_candles(24 * 40)
    signal_15d = mk_signal(24 * 15)  # 15 days of history -- too early for the default 30-day lookback
    default_regimes = gc.regime_by_signal_index([signal_15d], candles)
    assert signal_15d.index not in default_regimes

    tight_regimes = gc.regime_by_signal_index([signal_15d], candles, lookback_days=10)
    assert tight_regimes[signal_15d.index] == "bull"  # 15 days is enough history at a 10-day lookback


def test_regime_by_signal_index_custom_threshold_changes_classification():
    candles = rising_candles(24 * 40)
    signal = mk_signal(24 * 35)
    default_regimes = gc.regime_by_signal_index([signal], candles)
    assert default_regimes[signal.index] == "bull"  # default 5% threshold

    strict_regimes = gc.regime_by_signal_index([signal], candles, bull_threshold=5.0)
    assert strict_regimes[signal.index] == "range"  # far below a 500% threshold


# --- build_sensitivity_gate_configs (F6b I2 sensitivity follow-up) ---


def test_build_sensitivity_gate_configs_short_bull_has_nine_combinations():
    configs = gc.build_sensitivity_gate_configs("veto_short_bull")
    assert len(configs) == 9
    assert all(c.use_regime_direction_gate and not c.use_long_bear_veto for c in configs)
    assert {(c.regime_lookback_days, c.regime_threshold) for c in configs} == {
        (lb, th) for lb in gc.SENSITIVITY_LOOKBACK_DAYS_GRID for th in gc.SENSITIVITY_THRESHOLD_GRID
    }
    assert len({c.name for c in configs}) == 9  # names are unique, self-describing


def test_build_sensitivity_gate_configs_long_bear_uses_long_bear_flag():
    configs = gc.build_sensitivity_gate_configs("veto_long_bear")
    assert len(configs) == 9
    assert all(c.use_long_bear_veto and not c.use_regime_direction_gate for c in configs)


def test_build_sensitivity_gate_configs_rejects_unknown_mechanism():
    with pytest.raises(ValueError, match="mechanism"):
        gc.build_sensitivity_gate_configs("veto_something_else")


def test_run_gated_series_respects_custom_regime_threshold():
    candles = noisy_zigzag()
    baseline = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    strict = gc.run_gated_series(
        "synthetic", candles, gc.GateConfig(name="veto_short_bull_strict", use_regime_direction_gate=True, regime_threshold=0.99)
    )
    # threshold=0.99 is essentially unreachable on this fixture's bounded
    # price swings -- "bull" never classifies, so nothing gets vetoed and
    # kept count matches the unfiltered baseline exactly.
    assert strict.total_kept == baseline.total_kept


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


# --- F6b I2 follow-up v3: veto_long_bear (symmetric to veto_short_bull,
# weaker prior -- module docstring "VETO_LONG_BEAR") ---


def test_apply_gates_veto_long_bear_drops_long_in_bear_regime():
    test = [mk_labeled_dir(0, LONG), mk_labeled_dir(1, SHORT)]
    config = gc.GateConfig(name="veto_long_bear", use_long_bear_veto=True)
    kept = gc.apply_gates([], test, config, regime_by_index={0: "bear", 1: "bear"})
    assert [ls.signal.index for ls in kept] == [1]  # LONG vetoed, SHORT untouched even in a bear regime


def test_apply_gates_veto_long_bear_keeps_long_outside_bear_regime():
    test = [mk_labeled_dir(0, LONG), mk_labeled_dir(1, LONG)]
    config = gc.GateConfig(name="veto_long_bear", use_long_bear_veto=True)
    kept = gc.apply_gates([], test, config, regime_by_index={0: "bull", 1: "range"})
    assert {ls.signal.index for ls in kept} == {0, 1}


def test_apply_gates_veto_long_bear_keeps_long_with_unknown_regime():
    test = [mk_labeled_dir(0, LONG)]
    config = gc.GateConfig(name="veto_long_bear", use_long_bear_veto=True)
    kept = gc.apply_gates([], test, config, regime_by_index={})
    assert kept == test


def test_apply_gates_veto_long_bear_never_touches_short_bull_veto():
    # Both mechanisms can be requested together (independent booleans) --
    # each only ever vetoes its OWN direction x regime combination.
    test = [mk_labeled_dir(0, SHORT), mk_labeled_dir(1, LONG)]
    config = gc.GateConfig(name="both_regime_vetoes", use_regime_direction_gate=True, use_long_bear_veto=True)
    kept = gc.apply_gates([], test, config, regime_by_index={0: "bull", 1: "bear"})
    assert kept == []  # SHORT vetoed by short_bull (bull regime), LONG vetoed by long_bear (bear regime)


def test_apply_gates_ltf_override_keeps_long_with_fresh_bullish_choch():
    test = [mk_labeled_dir(0, LONG)]
    config = gc.GateConfig(name="veto_long_bear_ltf_override", use_long_bear_veto=True, use_ltf_fakeout_override=True)
    kept = gc.apply_gates(
        [], test, config, regime_by_index={0: "bear"}, ltf_events_by_index={0: _choch(ms.StructureBreakDirection.BULLISH)}
    )
    assert [ls.signal.index for ls in kept] == [0]  # fakeout confirmed -- override un-vetoes the LONG


def test_apply_gates_ltf_override_still_vetoes_long_on_bearish_choch():
    # Wrong direction (bearish) doesn't confirm a fakeout of the LONG
    # candidate's own direction -- must not override.
    test = [mk_labeled_dir(0, LONG)]
    config = gc.GateConfig(name="veto_long_bear_ltf_override", use_long_bear_veto=True, use_ltf_fakeout_override=True)
    kept = gc.apply_gates(
        [], test, config, regime_by_index={0: "bear"}, ltf_events_by_index={0: _choch(ms.StructureBreakDirection.BEARISH)}
    )
    assert kept == []


def test_apply_gates_ltf_override_never_affects_short_bull_veto_direction():
    # A bullish CHoCH override is only meaningful for a vetoed LONG -- a
    # SHORT vetoed by veto_short_bull still needs a BEARISH CHoCH, not this.
    test = [mk_labeled_dir(0, SHORT)]
    config = gc.GateConfig(
        name="both_ltf_override", use_regime_direction_gate=True, use_long_bear_veto=True, use_ltf_fakeout_override=True
    )
    kept = gc.apply_gates(
        [], test, config, regime_by_index={0: "bull"}, ltf_events_by_index={0: _choch(ms.StructureBreakDirection.BULLISH)}
    )
    assert kept == []  # wrong-direction CHoCH -- SHORT stays vetoed


def test_run_gated_series_veto_long_bear_never_increases_kept_count():
    candles = noisy_zigzag()
    baseline = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    result = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="veto_long_bear", use_long_bear_veto=True))
    assert result.total_kept <= baseline.total_kept


def test_run_gated_series_veto_long_bear_well_formed_result():
    candles = noisy_zigzag()
    result = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="veto_long_bear", use_long_bear_veto=True))
    assert result.gate_name == "veto_long_bear"
    assert result.total_windows >= 1
    assert 0 <= result.windows_passing_pf <= result.total_windows


def test_run_gated_series_veto_long_bear_ltf_override_requires_candles_15m():
    candles = noisy_zigzag()
    config = gc.GateConfig(name="veto_long_bear_ltf_override", use_long_bear_veto=True, use_ltf_fakeout_override=True)
    with pytest.raises(ValueError, match="candles_15m"):
        gc.run_gated_series("synthetic", candles, config)


def test_run_gated_series_veto_long_bear_ltf_override_never_increases_kept_count_vs_plain():
    candles = noisy_zigzag()
    candles_15m = noisy_zigzag_15m()
    plain = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="veto_long_bear", use_long_bear_veto=True))
    overridden = gc.run_gated_series(
        "synthetic", candles, gc.GateConfig(name="veto_long_bear_ltf_override", use_long_bear_veto=True, use_ltf_fakeout_override=True),
        candles_15m=candles_15m,
    )
    assert overridden.total_kept >= plain.total_kept


# --- run_gated_series_batch: shares signal generation, must match per-gate calls ---


def test_run_gated_series_batch_matches_individual_calls():
    candles = noisy_zigzag()
    configs = [gc.GateConfig(name="no_gate"), gc.GateConfig(name="trend_alignment_only", use_trend_alignment_gate=True)]
    batch_results = gc.run_gated_series_batch("synthetic", candles, configs)
    individual_results = [gc.run_gated_series("synthetic", candles, config) for config in configs]
    assert batch_results == individual_results


def test_run_gated_series_batch_returns_one_result_per_gate_config():
    candles = noisy_zigzag()
    candles_15m = noisy_zigzag_15m()
    results = gc.run_gated_series_batch("synthetic", candles, list(gc.GATE_CONFIGS), candles_15m=candles_15m)
    assert [r.gate_name for r in results] == [c.name for c in gc.GATE_CONFIGS]


def test_run_gated_series_batch_campaign_config_changes_signal_generation():
    candles = noisy_zigzag()
    f5_candidate = campaign.CAMPAIGN_CONFIGS[1]
    default_results = gc.run_gated_series_batch("synthetic", candles, [gc.GateConfig(name="no_gate")])
    candidate_results = gc.run_gated_series_batch("synthetic", candles, [gc.GateConfig(name="no_gate")], campaign_config=f5_candidate)
    assert candidate_results[0].total_signals != default_results[0].total_signals


# --- F6b I2 follow-up v2: LTF fakeout override (micro_structure_event /
# micro_structure_event_by_signal_index / apply_gates) ---


def _mk15(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(ts=datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(minutes=15 * i), open=o, high=h, low=l, close=c, volume=v)


def _flat15(n: int, start_price: float = 100.0) -> list[fgt.Candle]:
    return [_mk15(i, start_price, start_price + 0.05, start_price - 0.05, start_price) for i in range(n)]


def _leg15(candles: list[fgt.Candle], start_idx: int, delta_per_candle: float, n: int) -> list[fgt.Candle]:
    """Same strictly-monotonic-leg construction as test_fib_gann_timing.py's
    own monotonic_leg(), just building 15m-spaced candles directly rather
    than taking a generic `mk` -- this fixture is only ever used here."""
    last_close = candles[-1].close
    out = list(candles)
    for step in range(n):
        o = last_close
        c = o + delta_per_candle
        out.append(_mk15(start_idx + step, o, max(o, c), min(o, c), c))
        last_close = c
    return out


def _uptrend_then_bearish_choch_15m() -> tuple[list[fgt.Candle], int]:
    """Causal fixture for micro_structure_event(): establishes a clean 15m
    UPTREND (2 confirmed higher-highs + higher-lows, same W-shape
    construction test_fib_gann_timing.py's own detect_swings tests use)
    then breaks BEARISH below the most recent confirmed swing low -- the
    "fakeout failing" shape the LTF override (module docstring) exists to
    detect. Returns (candles, index where the breaking leg starts)."""
    candles = _flat15(20)
    candles = _leg15(candles, 20, 2.0, 10)  # up ~100 -> ~120
    candles = _leg15(candles, 30, -1.5, 8)  # pullback ~120 -> ~108 -- confirms swing HIGH ~120
    candles = _leg15(candles, 38, 2.0, 8)  # up ~108 -> ~124 -- confirms swing LOW ~108
    candles = _leg15(candles, 46, -1.5, 8)  # pullback ~124 -> ~112 -- confirms swing HIGH ~124
    candles = _leg15(candles, 54, 2.0, 8)  # up ~112 -> ~128 -- confirms swing LOW ~112 (now 2 highs + 2 lows -> UPTREND)
    break_start_idx = len(candles)
    candles = _leg15(candles, break_start_idx, -3.0, 10)  # sharp decline breaking below ~112 -- BEARISH CHoCH
    return candles, break_start_idx


def test_micro_structure_event_detects_fresh_bearish_choch_after_uptrend():
    candles, break_start_idx = _uptrend_then_bearish_choch_15m()
    candles_ts = [c.ts for c in candles]
    as_of = candles[break_start_idx + 8].ts  # well into the decline, clearly below the ~112 swing low
    event = gc.micro_structure_event(candles_ts, candles, as_of)
    assert event is not None
    assert event.event_type is ms.StructureEventType.CHOCH
    assert event.break_direction is ms.StructureBreakDirection.BEARISH


def test_micro_structure_event_no_lookahead_before_the_break():
    candles, break_start_idx = _uptrend_then_bearish_choch_15m()
    candles_ts = [c.ts for c in candles]
    as_of = candles[break_start_idx - 1].ts  # right before the decline starts
    event = gc.micro_structure_event(candles_ts, candles, as_of)
    is_bearish_choch = event is not None and event.event_type is ms.StructureEventType.CHOCH and event.break_direction is ms.StructureBreakDirection.BEARISH
    assert not is_bearish_choch  # the future break must not be visible yet


def test_micro_structure_event_stale_choch_outside_lookback_window_not_seen():
    candles, _ = _uptrend_then_bearish_choch_15m()
    # Long flat tail, well past LTF_LOOKBACK_CANDLES -- the fresh CHoCH
    # detected right after the break must stop being "seen" once it falls
    # outside the bounded trailing window (module docstring: freshness is
    # the whole point of bounding this window, not just performance).
    tail_start = candles[-1].ts
    tail_price = candles[-1].close
    tail = [
        fgt.Candle(
            ts=tail_start + datetime.timedelta(minutes=15 * (i + 1)),
            open=tail_price, high=tail_price + 0.05, low=tail_price - 0.05, close=tail_price, volume=100.0,
        )
        for i in range(gc.LTF_LOOKBACK_CANDLES + 50)
    ]
    full = candles + tail
    candles_ts = [c.ts for c in full]
    event = gc.micro_structure_event(candles_ts, full, full[-1].ts)
    assert event is None  # window is now pure flat noise -- no swings, no event


def test_micro_structure_event_none_before_first_candle():
    candles, _ = _uptrend_then_bearish_choch_15m()
    candles_ts = [c.ts for c in candles]
    before_series = candles_ts[0] - datetime.timedelta(minutes=15)
    assert gc.micro_structure_event(candles_ts, candles, before_series) is None


def test_micro_structure_event_none_with_too_few_candles():
    candles = _flat15(5)
    candles_ts = [c.ts for c in candles]
    assert gc.micro_structure_event(candles_ts, candles, candles_ts[-1]) is None


def test_micro_structure_event_by_signal_index_maps_each_signal():
    candles, break_start_idx = _uptrend_then_bearish_choch_15m()
    before_signal = dataclasses.replace(mk_signal(0), ts=candles[break_start_idx - 1].ts, index=0)
    after_signal = dataclasses.replace(mk_signal(1), ts=candles[break_start_idx + 8].ts, index=1)
    events = gc.micro_structure_event_by_signal_index([before_signal, after_signal], candles)
    assert set(events) == {0, 1}
    assert events[1] is not None
    assert events[1].event_type is ms.StructureEventType.CHOCH
    assert events[1].break_direction is ms.StructureBreakDirection.BEARISH


# --- apply_gates: veto_short_bull_ltf_override ---


def _choch(break_direction: ms.StructureBreakDirection) -> ms.StructureEvent:
    return ms.StructureEvent(
        event_type=ms.StructureEventType.CHOCH, break_direction=break_direction, trend_bias_before=ms.TrendBias.UPTREND, broken_level=100.0
    )


def _bos(break_direction: ms.StructureBreakDirection) -> ms.StructureEvent:
    return ms.StructureEvent(
        event_type=ms.StructureEventType.BOS, break_direction=break_direction, trend_bias_before=ms.TrendBias.DOWNTREND, broken_level=100.0
    )


def test_apply_gates_ltf_override_keeps_short_with_fresh_bearish_choch():
    test = [mk_labeled_dir(0, SHORT)]
    config = gc.GateConfig(name="veto_short_bull_ltf_override", use_regime_direction_gate=True, use_ltf_fakeout_override=True)
    kept = gc.apply_gates(
        [], test, config, regime_by_index={0: "bull"}, ltf_events_by_index={0: _choch(ms.StructureBreakDirection.BEARISH)}
    )
    assert [ls.signal.index for ls in kept] == [0]  # fakeout confirmed -- override un-vetoes the SHORT


def test_apply_gates_ltf_override_still_vetoes_without_an_event():
    test = [mk_labeled_dir(0, SHORT)]
    config = gc.GateConfig(name="veto_short_bull_ltf_override", use_regime_direction_gate=True, use_ltf_fakeout_override=True)
    kept = gc.apply_gates([], test, config, regime_by_index={0: "bull"}, ltf_events_by_index={0: None})
    assert kept == []


def test_apply_gates_ltf_override_still_vetoes_on_bullish_choch():
    # A CHoCH in the WRONG direction (bullish) doesn't confirm a fakeout of
    # the SHORT candidate's own direction -- must not override.
    test = [mk_labeled_dir(0, SHORT)]
    config = gc.GateConfig(name="veto_short_bull_ltf_override", use_regime_direction_gate=True, use_ltf_fakeout_override=True)
    kept = gc.apply_gates(
        [], test, config, regime_by_index={0: "bull"}, ltf_events_by_index={0: _choch(ms.StructureBreakDirection.BULLISH)}
    )
    assert kept == []


def test_apply_gates_ltf_override_still_vetoes_on_bearish_bos_not_choch():
    # A bearish BOS presupposes a downtrend already established at 15m --
    # a different, not-yet-tested question from a fresh CHoCH (module
    # docstring's "open questions") -- only CHOCH counts as the override
    # trigger for now.
    test = [mk_labeled_dir(0, SHORT)]
    config = gc.GateConfig(name="veto_short_bull_ltf_override", use_regime_direction_gate=True, use_ltf_fakeout_override=True)
    kept = gc.apply_gates(
        [], test, config, regime_by_index={0: "bull"}, ltf_events_by_index={0: _bos(ms.StructureBreakDirection.BEARISH)}
    )
    assert kept == []


def test_apply_gates_ltf_override_never_affects_long():
    test = [mk_labeled_dir(0, LONG)]
    config = gc.GateConfig(name="veto_short_bull_ltf_override", use_regime_direction_gate=True, use_ltf_fakeout_override=True)
    kept = gc.apply_gates([], test, config, regime_by_index={0: "bull"}, ltf_events_by_index={0: _choch(ms.StructureBreakDirection.BEARISH)})
    assert kept == test  # LONG was never vetoed in the first place -- nothing to override


def test_apply_gates_ltf_override_noop_without_regime_direction_gate():
    # use_ltf_fakeout_override alone (without use_regime_direction_gate)
    # has nothing to override -- confirms it never vetoes on its own.
    test = [mk_labeled_dir(0, SHORT)]
    config = gc.GateConfig(name="ltf_only", use_ltf_fakeout_override=True)
    kept = gc.apply_gates([], test, config, regime_by_index={0: "bull"}, ltf_events_by_index={0: None})
    assert kept == test


# --- apply_gates: LTF fakeout override v2 (require_major_regime_conflict) ---


def _major_conflict_config(**kwargs) -> gc.GateConfig:
    return gc.GateConfig(
        name="veto_short_bull_ltf_override_major_conflict", use_regime_direction_gate=True, use_ltf_fakeout_override=True,
        require_major_regime_conflict=True, **kwargs,
    )


def test_apply_gates_major_conflict_overrides_when_major_regime_disagrees():
    # Local (30-day) regime says bull -- triggers the veto -- but the
    # major (90-day) regime is bear, confirming a real major/local
    # conflict (the founder's "fakeout inside a larger downtrend" case).
    test = [mk_labeled_dir(0, SHORT)]
    config = _major_conflict_config()
    kept = gc.apply_gates(
        [], test, config,
        regime_by_index={0: "bull"},
        ltf_events_by_index={0: _choch(ms.StructureBreakDirection.BEARISH)},
        major_regime_by_index={0: "bear"},
    )
    assert [ls.signal.index for ls in kept] == [0]


def test_apply_gates_major_conflict_stays_vetoed_when_major_regime_agrees():
    # Major regime is ALSO bull -- this is an ordinary pullback inside a
    # genuine sustained uptrend, not a fakeout -- v1's failure mode
    # (Section 33) this redesign exists to fix. Must stay vetoed even
    # though a same-direction CHoCH fired.
    test = [mk_labeled_dir(0, SHORT)]
    config = _major_conflict_config()
    kept = gc.apply_gates(
        [], test, config,
        regime_by_index={0: "bull"},
        ltf_events_by_index={0: _choch(ms.StructureBreakDirection.BEARISH)},
        major_regime_by_index={0: "bull"},
    )
    assert kept == []


def test_apply_gates_major_conflict_range_counts_as_conflict():
    # "Major regime is NOT bull" is the deliberately loose reading of
    # conflict (module docstring) -- "range" (not a confirmed bull either)
    # also counts, not just strict "bear".
    test = [mk_labeled_dir(0, SHORT)]
    config = _major_conflict_config()
    kept = gc.apply_gates(
        [], test, config,
        regime_by_index={0: "bull"},
        ltf_events_by_index={0: _choch(ms.StructureBreakDirection.BEARISH)},
        major_regime_by_index={0: "range"},
    )
    assert [ls.signal.index for ls in kept] == [0]


def test_apply_gates_major_conflict_unknown_major_regime_stays_vetoed():
    # Too early in the series for 90 days of major-regime history -- can't
    # confirm a conflict, so it stays vetoed (can't-decide fallback, same
    # precedent as every other gate here), even with a matching CHoCH.
    test = [mk_labeled_dir(0, SHORT)]
    config = _major_conflict_config()
    kept = gc.apply_gates(
        [], test, config,
        regime_by_index={0: "bull"},
        ltf_events_by_index={0: _choch(ms.StructureBreakDirection.BEARISH)},
        major_regime_by_index={},
    )
    assert kept == []


def test_apply_gates_major_conflict_still_requires_a_choch_too():
    # A confirmed major/local conflict alone isn't enough -- still needs
    # the same-direction CHoCH v1 already required.
    test = [mk_labeled_dir(0, SHORT)]
    config = _major_conflict_config()
    kept = gc.apply_gates(
        [], test, config,
        regime_by_index={0: "bull"},
        ltf_events_by_index={0: None},
        major_regime_by_index={0: "bear"},
    )
    assert kept == []


def test_apply_gates_major_conflict_symmetric_for_long_bear():
    test = [mk_labeled_dir(0, LONG)]
    config = gc.GateConfig(
        name="veto_long_bear_ltf_override_major_conflict", use_long_bear_veto=True, use_ltf_fakeout_override=True,
        require_major_regime_conflict=True,
    )
    kept = gc.apply_gates(
        [], test, config,
        regime_by_index={0: "bear"},
        ltf_events_by_index={0: _choch(ms.StructureBreakDirection.BULLISH)},
        major_regime_by_index={0: "bull"},  # major disagrees with the local "bear" -- confirms conflict
    )
    assert [ls.signal.index for ls in kept] == [0]


def test_run_gated_series_major_conflict_never_increases_kept_count_vs_no_gate():
    candles = noisy_zigzag()
    candles_15m = noisy_zigzag_15m()
    baseline = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="no_gate"))
    result = gc.run_gated_series(
        "synthetic", candles,
        gc.GateConfig(
            name="veto_short_bull_ltf_override_major_conflict", use_regime_direction_gate=True, use_ltf_fakeout_override=True,
            require_major_regime_conflict=True,
        ),
        candles_15m=candles_15m,
    )
    assert result.total_kept <= baseline.total_kept


# --- run_gated_series: veto_short_bull_ltf_override requires candles_15m ---


def test_run_gated_series_ltf_override_requires_candles_15m():
    candles = noisy_zigzag()
    config = gc.GateConfig(name="veto_short_bull_ltf_override", use_regime_direction_gate=True, use_ltf_fakeout_override=True)
    with pytest.raises(ValueError, match="candles_15m"):
        gc.run_gated_series("synthetic", candles, config)  # candles_15m omitted -- must fail loud, not silently degrade


def test_run_gated_series_ltf_override_never_increases_kept_count_vs_veto_short_bull():
    # The override can only ADD BACK signals veto_short_bull alone would
    # drop -- so kept count for the override variant is always >= plain
    # veto_short_bull's, but both stay <= no_gate (already covered above).
    candles = noisy_zigzag()
    candles_15m = noisy_zigzag_15m()
    plain = gc.run_gated_series("synthetic", candles, gc.GateConfig(name="veto_short_bull", use_regime_direction_gate=True))
    overridden = gc.run_gated_series(
        "synthetic", candles, gc.GateConfig(name="veto_short_bull_ltf_override", use_regime_direction_gate=True, use_ltf_fakeout_override=True),
        candles_15m=candles_15m,
    )
    assert overridden.total_kept >= plain.total_kept
