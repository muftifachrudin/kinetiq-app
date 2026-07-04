import datetime
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "validation" / "fib_gann_backtest"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import derivatives_context as dc  # noqa: E402
import fib_gann_timing as fgt  # noqa: E402
import signal_runner as sr  # noqa: E402

UTC = datetime.timezone.utc


def mk(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(
        ts=datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=i), open=o, high=h, low=l, close=c, volume=v
    )


def monotonic_leg(candles: list[fgt.Candle], start_idx: int, delta_per_candle: float, n: int) -> list[fgt.Candle]:
    last_close = candles[-1].close
    out = list(candles)
    for step in range(n):
        o = last_close
        c = o + delta_per_candle
        out.append(mk(start_idx + step, o, max(o, c), min(o, c), c))
        last_close = c
    return out


def noisy_zigzag(n: int = 120, seed: int = 42) -> list[fgt.Candle]:
    """A wandering series with a reversal roughly every 15 bars -- enough
    genuine structure for detect_swings to confirm multiple pivots,
    unlike a pure trend or pure noise series."""
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


# --- _entry_is_valid ---


def test_entry_is_valid_long_true_when_entry_above_stop_loss():
    assert sr._entry_is_valid(fgt.TradeDirection.LONG, entry_price=110.0, stop_loss=105.0) is True


def test_entry_is_valid_long_false_when_entry_at_or_below_stop_loss():
    # real-data catch (3 Juli 2026, BTC/USDT 1h): a later candle's close
    # can fall below the SL level derived from an already-confirmed LONG
    # pivot -- the trade's premise is broken before entry exists.
    assert sr._entry_is_valid(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=105.0) is False
    assert sr._entry_is_valid(fgt.TradeDirection.LONG, entry_price=105.0, stop_loss=105.0) is False


def test_entry_is_valid_short_true_when_entry_below_stop_loss():
    assert sr._entry_is_valid(fgt.TradeDirection.SHORT, entry_price=90.0, stop_loss=95.0) is True


def test_entry_is_valid_short_false_when_entry_at_or_above_stop_loss():
    assert sr._entry_is_valid(fgt.TradeDirection.SHORT, entry_price=100.0, stop_loss=95.0) is False
    assert sr._entry_is_valid(fgt.TradeDirection.SHORT, entry_price=95.0, stop_loss=95.0) is False


# --- generate_signals ---


def test_generate_signals_empty_candles_returns_empty_list():
    assert sr.generate_signals([]) == []


def test_generate_signals_insufficient_candles_returns_empty_list():
    candles = [mk(i, 100, 101, 99, 100) for i in range(10)]  # well under DEFAULT_ATR_PERIOD + 2
    assert sr.generate_signals(candles) == []


def test_generate_signals_invariants_hold_on_noisy_series():
    candles = noisy_zigzag()
    signals = sr.generate_signals(candles)
    assert signals, "expected at least one signal from a 120-candle wandering series"
    for s in signals:
        assert sr._entry_is_valid(s.direction, s.entry_price, s.exit_plan.stop_loss)
        assert s.exit_plan.risk_reward_ratio is not None
        assert s.exit_plan.risk_reward_ratio >= fgt.DEFAULT_MIN_RR_THRESHOLD
        assert 0.0 <= s.confidence <= 1.0
        assert s.exit_plan.take_profits
        tp1 = s.exit_plan.take_profits[0]
        if s.direction is fgt.TradeDirection.LONG:
            assert tp1 > s.entry_price
        else:
            assert tp1 < s.entry_price
        # a signal can only be emitted once its own pivot has been confirmed
        assert s.index >= s.pivot.index


def test_generate_signals_fires_on_touch_bar_not_confirmation_bar():
    # founder-confirmed entry trigger (3 Juli 2026): a signal fires when
    # price actually touches a fib/gann line, which happens on a LATER
    # bar than pivot confirmation (the pivot itself confirms with a lag,
    # so there's essentially never confluence right at that exact bar).
    # This is a real behavioral property of the wandering synthetic
    # series, not a contrived edge case -- every signal in this fixture
    # fires strictly after its own pivot confirms.
    candles = noisy_zigzag()
    signals = sr.generate_signals(candles)
    assert signals
    for s in signals:
        assert s.index > s.pivot.index, "signal fired exactly at pivot confirmation -- touch-watching isn't happening"


def test_generate_signals_every_signal_is_a_genuine_fib_gann_touch():
    # cross-check each emitted signal against an independently
    # recomputed fib_gann_confluence_score at its own firing bar --
    # proves the touch condition the docstring promises actually holds,
    # not just that some delay happened to elapse.
    candles = noisy_zigzag()
    signals = sr.generate_signals(candles)
    assert signals
    atr_series = fgt.compute_atr(candles)
    for s in signals:
        gann_prices = fgt.gann_fan_prices(s.pivot, s.basis_leg_start, bar_index=s.index)
        swing_low = min(s.pivot.price, s.basis_leg_start.price)
        swing_high = max(s.pivot.price, s.basis_leg_start.price)
        fib_levels = fgt.compute_fib_levels(swing_low, swing_high)
        score = fgt.fib_gann_confluence_score(fib_levels, gann_prices, candles[s.index].close, atr_series[s.index])
        assert score > 0.0


def test_generate_signals_failed_touch_does_not_block_a_later_touch():
    # exact naturally-occurring case from noisy_zigzag()'s default seed:
    # pivot 29 touches a fib/gann line at bar 31 (fib_gann_confluence >
    # 0) but fails the R:R gate there (no take_profits found), then
    # touches again at bar 32 and succeeds. The final signal must be the
    # bar-32 one, not silently dropped because bar 31 already "used up"
    # this pivot.
    candles = noisy_zigzag()
    atr_series = fgt.compute_atr(candles)

    def confluence_at(bar_index, pivot, basis):
        gann_prices = fgt.gann_fan_prices(pivot, basis, bar_index=bar_index)
        swing_low = min(pivot.price, basis.price)
        swing_high = max(pivot.price, basis.price)
        fib_levels = fgt.compute_fib_levels(swing_low, swing_high)
        return fgt.fib_gann_confluence_score(fib_levels, gann_prices, candles[bar_index].close, atr_series[bar_index])

    swings_31 = fgt.detect_swings(candles, as_of=candles[31].ts)
    pivot, basis = swings_31[-1], swings_31[-2]
    assert pivot.index == 29
    assert confluence_at(31, pivot, basis) > 0.0  # touch #1: exists, but...
    exit_plan_31 = fgt.build_exit_plan(pivot, basis, candles[31].close, atr_series[31], fgt.gann_fan_prices(pivot, basis, 31))
    assert not fgt.passes_risk_reward_gate(exit_plan_31)  # ...fails the R:R gate
    assert confluence_at(32, pivot, basis) > 0.0  # touch #2: also a real touch

    signals = sr.generate_signals(candles)
    matching = [s for s in signals if s.pivot.index == 29]
    assert len(matching) == 1
    assert matching[0].index == 32


def test_generate_signals_no_duplicate_signals_for_same_persisting_pivot():
    # one clean reversal (confirms a HIGH then a LOW pivot), then a long
    # flat stretch where neither swing changes -- must not re-signal on
    # every one of those flat bars for the same underlying pivot.
    candles = [mk(i, 100, 100.5, 99.5, 100) for i in range(20)]  # ATR warmup, flat
    candles = monotonic_leg(candles, 20, -3.0, 10)  # confirms a HIGH pivot on reversal
    candles = monotonic_leg(candles, 30, 3.0, 10)  # confirms a LOW pivot on reversal
    candles = candles + [mk(i, candles[-1].close, candles[-1].close + 0.1, candles[-1].close - 0.1, candles[-1].close) for i in range(40, 80)]

    signals = sr.generate_signals(candles)
    pivot_indices = [s.pivot.index for s in signals]
    assert len(pivot_indices) == len(set(pivot_indices)), f"duplicate signals for the same pivot: {pivot_indices}"


def test_generate_signals_direction_matches_pivot_swing_direction():
    candles = noisy_zigzag(seed=7)
    signals = sr.generate_signals(candles)
    for s in signals:
        expected = fgt.TradeDirection.LONG if s.pivot.direction is fgt.SwingDirection.LOW else fgt.TradeDirection.SHORT
        assert s.direction is expected


def test_generate_signals_accepts_custom_min_rr_threshold():
    candles = noisy_zigzag()
    lenient = sr.generate_signals(candles, min_rr_threshold=0.0)
    strict = sr.generate_signals(candles, min_rr_threshold=100.0)
    assert len(lenient) >= len(strict)
    assert strict == []


def test_generate_signals_accepts_max_rr_threshold_cap():
    # Fase 5: an extremely tight cap should filter out every signal whose
    # R:R is real (min_rr_threshold=0.0 lets everything with a TP1 through
    # first, so this isolates the max cap's own effect).
    candles = noisy_zigzag()
    uncapped = sr.generate_signals(candles, min_rr_threshold=0.0, max_rr_threshold=None)
    capped = sr.generate_signals(candles, min_rr_threshold=0.0, max_rr_threshold=0.001)
    assert len(uncapped) >= len(capped)
    assert capped == []


def test_generate_signals_accepts_next_fib_level_sl_method():
    # Fase 5: switching sl_method must not crash the full walk and must
    # produce a genuinely different stop_loss than the ATR-buffer default
    # for at least one signal (same series, same everything else).
    candles = noisy_zigzag()
    atr_buffer_signals = sr.generate_signals(candles)
    next_fib_signals = sr.generate_signals(candles, sl_method=fgt.StopLossMethod.NEXT_FIB_LEVEL)
    assert atr_buffer_signals  # sanity: this series does produce signals at all
    assert next_fib_signals
    atr_stop_losses = [s.exit_plan.stop_loss for s in atr_buffer_signals]
    next_fib_stop_losses = [s.exit_plan.stop_loss for s in next_fib_signals]
    assert atr_stop_losses != next_fib_stop_losses


def test_generate_signals_populates_per_factor_dump_fields():
    # Fase 3 (docs/sonnet5-implementation-roadmap.md): every emitted
    # Signal must carry real computed per-factor values, not the
    # dataclass's own 0.5 placeholder defaults (those defaults exist only
    # for old test call sites that construct a Signal by hand and don't
    # care about these fields -- generate_signals() itself always fills
    # them in for real).
    candles = noisy_zigzag()
    signals = sr.generate_signals(candles)
    assert signals
    for s in signals:
        for value in (
            s.swing_quality, s.fib_gann_confluence, s.volume_confirmation, s.wick_rejection,
            s.structure_alignment, s.htf_alignment, s.regime_alignment, s.sma_trend_bias_alignment,
            s.funding_contrarian_alignment, s.global_ls_contrarian_alignment, s.top_vs_global_alignment,
        ):
            assert 0.0 <= value <= 1.0
        assert s.fib_gann_confluence > 0.0  # the touch-trigger condition itself guarantees this
        assert s.wick_rejection == s.pivot.wick_rejection_score
        assert s.regime_alignment == s.structure_alignment  # see Signal's own docstring on why these match today
        # no derivatives_records passed -- Fase 4 fields must stay at their neutral defaults
        assert s.funding_contrarian_alignment == 0.5
        assert s.global_ls_contrarian_alignment == 0.5
        assert s.top_vs_global_alignment == 0.5
        assert s.liq_cascade_flag == 0.0


def test_generate_signals_wires_derivatives_context_when_records_supplied():
    candles = noisy_zigzag()
    base_date = candles[0].ts.date()
    # Extreme funding_rate ramp over a long trailing window so every
    # signal's own day sits near the top of its trailing percentile --
    # deliberately far more days than the candle series covers, so every
    # signal (whatever date it fires on) has a full window behind it.
    records = [
        dc.DailyDerivativesRecord(
            date=base_date - datetime.timedelta(days=400 - i),
            price_close=100.0 + i,
            oi_close=1000.0 + i,
            funding_rate=0.0001 * i,
            global_ls_ratio=1.0,
            top_ls_ratio=1.0,
        )
        for i in range(400)
    ]
    without = sr.generate_signals(candles)
    with_derivatives = sr.generate_signals(candles, derivatives_records=records)
    assert len(with_derivatives) == len(without)
    for s in with_derivatives:
        # funding_rate ramps monotonically up to "today" (the day before
        # any signal date, all comfortably inside the synthetic ramp) --
        # every signal's day sits near the top of the trailing window, so
        # LONG signals (contrarian-bearish) should score low alignment.
        if s.direction is fgt.TradeDirection.LONG:
            assert s.funding_contrarian_alignment < 0.5
        else:
            assert s.funding_contrarian_alignment > 0.5
