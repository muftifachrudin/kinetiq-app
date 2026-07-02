import datetime
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402

UTC = datetime.timezone.utc


def mk(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(
        ts=datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=i), open=o, high=h, low=l, close=c, volume=v
    )


def flat_noise(n: int, start_price: float = 100.0, seed: int = 1) -> list[fgt.Candle]:
    rng = random.Random(seed)
    candles = []
    for i in range(n):
        o = start_price + rng.uniform(-0.2, 0.2)
        c = o + rng.uniform(-0.2, 0.2)
        candles.append(mk(i, o, o + 0.3, o - 0.3, c))
    return candles


def monotonic_leg(candles: list[fgt.Candle], start_idx: int, delta_per_candle: float, n: int) -> list[fgt.Candle]:
    """Extends candles with n strictly-monotonic candles (no wick reversal
    possible), each candle's open chained from the previous close."""
    last_close = candles[-1].close
    out = list(candles)
    for step in range(n):
        o = last_close
        c = o + delta_per_candle
        out.append(mk(start_idx + step, o, max(o, c), min(o, c), c))
        last_close = c
    return out


# --- Candle / naive datetime rejection ---


def test_candle_rejects_naive_datetime():
    with pytest.raises(ValueError, match="timezone-aware"):
        fgt.Candle(ts=datetime.datetime(2024, 1, 1), open=1, high=1, low=1, close=1, volume=1)


def test_detect_swings_rejects_naive_as_of():
    candles = flat_noise(20)
    with pytest.raises(ValueError, match="timezone-aware"):
        fgt.detect_swings(candles, as_of=datetime.datetime(2024, 1, 1))


# --- compute_atr ---


def test_atr_converges_to_constant_true_range():
    candles = [mk(i, 100, 102, 98, 100) for i in range(30)]  # constant TR = 4.0 every candle
    atr = fgt.compute_atr(candles, period=14)
    assert atr[:14] == [None] * 14
    assert atr[14] == pytest.approx(4.0)
    assert atr[20] == pytest.approx(4.0)


def test_atr_too_few_candles_returns_all_none():
    candles = [mk(i, 100, 101, 99, 100) for i in range(5)]
    atr = fgt.compute_atr(candles, period=14)
    assert atr == [None] * 5


# --- detect_swings: the core algorithm ---


def test_detect_swings_strictly_monotonic_v_shape_yields_exactly_two_pivots():
    # A single clean drop then rally must yield exactly one HIGH then one
    # LOW -- catches the real bug found during manual testing where
    # checking a reversal against an extreme freshly updated by the same
    # candle degenerated into comparing a candle's own range to threshold,
    # firing a spurious pivot on nearly every candle of a sustained move.
    candles = flat_noise(20)
    candles = monotonic_leg(candles, 20, -2.0, 10)
    candles = monotonic_leg(candles, 30, 2.5, 10)
    swings = fgt.detect_swings(candles, atr_period=14, atr_multiplier=1.75)
    assert [s.direction for s in swings] == [fgt.SwingDirection.HIGH, fgt.SwingDirection.LOW]
    assert 17 <= swings[0].index <= 20
    assert 28 <= swings[1].index <= 30


def test_detect_swings_w_shape_yields_four_alternating_pivots():
    candles = flat_noise(20, seed=7)
    candles = monotonic_leg(candles, 20, -2.0, 10)  # down to ~80
    candles = monotonic_leg(candles, 30, 1.5, 8)  # partial rally to ~92
    candles = monotonic_leg(candles, 38, -2.0, 8)  # down again to ~76
    candles = monotonic_leg(candles, 46, 2.5, 10)  # rally to new high (unconfirmed, no reversal after)
    swings = fgt.detect_swings(candles, atr_period=14, atr_multiplier=1.75)
    assert [s.direction for s in swings] == [
        fgt.SwingDirection.HIGH,
        fgt.SwingDirection.LOW,
        fgt.SwingDirection.HIGH,
        fgt.SwingDirection.LOW,
    ]
    # strictly alternating and strictly increasing index
    for a, b in zip(swings, swings[1:]):
        assert a.index < b.index
        assert a.direction != b.direction


def test_detect_swings_too_few_candles_returns_empty():
    candles = flat_noise(5)
    assert fgt.detect_swings(candles, atr_period=14) == []


def test_detect_swings_no_lookahead():
    candles = flat_noise(20, seed=1)
    candles = monotonic_leg(candles, 20, -2.0, 10)
    candles = monotonic_leg(candles, 30, 2.5, 10)
    full = fgt.detect_swings(candles)
    assert len(full) == 2

    # as_of before the low has formed: only the high should be visible
    cutoff = candles[25].ts
    partial = fgt.detect_swings(candles, as_of=cutoff)
    assert all(s.index <= 25 for s in partial)
    assert partial == full[:1]

    # as_of before any move at all: no swings yet
    assert fgt.detect_swings(candles, as_of=candles[19].ts) == []


# --- wick_rejection_score ---


def test_wick_rejection_score_long_lower_wick_scores_high_for_low_direction():
    c = mk(0, 100, 101, 90, 100.5)
    assert fgt.wick_rejection_score(c, fgt.SwingDirection.LOW) == pytest.approx((100 - 90) / (101 - 90))
    assert fgt.wick_rejection_score(c, fgt.SwingDirection.HIGH) < 0.1


def test_wick_rejection_score_zero_range_candle_returns_zero():
    c = mk(0, 100, 100, 100, 100)
    assert fgt.wick_rejection_score(c, fgt.SwingDirection.LOW) == 0.0


# --- swing_quality ---


def test_swing_quality_higher_for_more_violent_displacement_candle():
    candles = flat_noise(20, seed=3)
    # two otherwise-identical series, differing only in how violently the
    # pivot candle itself moved -- the more violent one should score higher.
    mild = monotonic_leg(candles, 20, -1.8, 3)  # barely crosses threshold
    violent = monotonic_leg(candles, 20, -6.0, 3)  # blows well past threshold in one candle
    mild_swings = fgt.detect_swings(mild, atr_period=14, atr_multiplier=1.75)
    violent_swings = fgt.detect_swings(violent, atr_period=14, atr_multiplier=1.75)
    assert mild_swings and violent_swings
    mild_quality = fgt.swing_quality(mild_swings[0], mild)
    violent_quality = fgt.swing_quality(violent_swings[0], violent)
    assert violent_quality >= mild_quality


def test_swing_quality_zero_for_index_zero():
    candles = flat_noise(20)
    swing = fgt.SwingPoint(index=0, ts=candles[0].ts, price=100, direction=fgt.SwingDirection.LOW, wick_rejection_score=0)
    assert fgt.swing_quality(swing, candles) == 0.0


# --- volume_confirmation ---


def test_volume_confirmation_spike_vs_rolling_average():
    candles = [mk(i, 100, 101, 99, 100, v=100) for i in range(25)]
    candles[20] = mk(20, 100, 101, 99, 100, v=400)
    swing = fgt.SwingPoint(index=20, ts=candles[20].ts, price=100, direction=fgt.SwingDirection.LOW, wick_rejection_score=0)
    assert fgt.volume_confirmation(swing, candles, lookback=20) == pytest.approx(4.0)


def test_volume_confirmation_no_prior_candles_returns_zero():
    candles = [mk(0, 100, 101, 99, 100, v=100)]
    swing = fgt.SwingPoint(index=0, ts=candles[0].ts, price=100, direction=fgt.SwingDirection.LOW, wick_rejection_score=0)
    assert fgt.volume_confirmation(swing, candles) == 0.0


# --- compute_fib_levels ---


def test_compute_fib_levels_founder_default_set():
    levels = fgt.compute_fib_levels(swing_low=80.0, swing_high=100.0)
    assert levels["retracement"][0.618] == pytest.approx(100 - 0.618 * 20)
    assert levels["retracement"][0.886] == pytest.approx(100 - 0.886 * 20)
    assert levels["extension"][1.618] == pytest.approx(100 - 1.618 * 20)
    assert set(levels["retracement"]) == set(fgt.DEFAULT_FIB_RETRACEMENT_LEVELS)
    assert set(levels["extension"]) == set(fgt.DEFAULT_FIB_EXTENSION_LEVELS)


def test_compute_fib_levels_rejects_inverted_swing():
    with pytest.raises(ValueError, match="must be greater than"):
        fgt.compute_fib_levels(swing_low=100.0, swing_high=80.0)


def test_compute_fib_levels_accepts_custom_levels():
    levels = fgt.compute_fib_levels(swing_low=0.0, swing_high=100.0, retracement_levels=(0.5,), extension_levels=())
    assert levels["retracement"] == {0.5: 50.0}
    assert levels["extension"] == {}


# --- Gann Fan ---


def sw(index: int, price: float, direction: fgt.SwingDirection) -> fgt.SwingPoint:
    return fgt.SwingPoint(
        index=index, ts=mk(index, price, price, price, price).ts, price=price, direction=direction, wick_rejection_score=0.0
    )


def test_gann_base_rate():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    assert fgt.gann_base_rate(pivot, basis) == pytest.approx(2.0)  # 20 price / 10 bars


def test_gann_base_rate_rejects_non_positive_duration():
    basis = sw(20, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)  # same index as basis
    with pytest.raises(ValueError, match="must be before"):
        fgt.gann_base_rate(pivot, basis)


def test_gann_fan_prices_all_angles_equal_pivot_price_at_pivot_bar():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    prices = fgt.gann_fan_prices(pivot, basis, bar_index=pivot.index)
    assert set(prices) == set(fgt.GANN_ANGLES)
    assert all(p == pytest.approx(80.0) for p in prices.values())


def test_gann_fan_prices_low_pivot_projects_upward_and_returns_to_swing_high_after_equal_duration():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    prices = fgt.gann_fan_prices(pivot, basis, bar_index=30)  # pivot.index + duration(10)
    assert prices["1x1"] == pytest.approx(100.0)
    assert prices["2x1"] > prices["1x1"] > prices["1x2"]  # steeper angle is higher for an upward fan


def test_gann_fan_prices_high_pivot_projects_downward_and_returns_to_swing_low_after_equal_duration():
    basis = sw(10, 80.0, fgt.SwingDirection.LOW)
    pivot = sw(20, 100.0, fgt.SwingDirection.HIGH)
    prices = fgt.gann_fan_prices(pivot, basis, bar_index=30)
    assert prices["1x1"] == pytest.approx(80.0)
    assert prices["2x1"] < prices["1x1"] < prices["1x2"]  # steeper angle is lower for a downward fan


def test_gann_fan_prices_accepts_custom_angle_subset():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    prices = fgt.gann_fan_prices(pivot, basis, bar_index=25, angles={"1x1": 1.0})
    assert set(prices) == {"1x1"}


# --- fib_confluence_score ---


def test_fib_confluence_score_near_a_level_scores_high():
    levels = fgt.compute_fib_levels(swing_low=80.0, swing_high=100.0)
    level_price = levels["retracement"][0.618]  # 87.64
    score = fgt.fib_confluence_score(levels, reference_price=level_price + 0.05, atr_value=1.0)
    assert score > 0.9


def test_fib_confluence_score_far_from_any_level_is_zero():
    levels = fgt.compute_fib_levels(swing_low=80.0, swing_high=100.0)
    # design brief: overlap > 0.5x ATR must NOT count as confluence
    score = fgt.fib_confluence_score(levels, reference_price=93.0, atr_value=1.0)
    assert score == 0.0


def test_fib_confluence_score_zero_atr_returns_zero_not_error():
    levels = fgt.compute_fib_levels(swing_low=80.0, swing_high=100.0)
    assert fgt.fib_confluence_score(levels, reference_price=87.64, atr_value=0.0) == 0.0


# --- fib_gann_confluence_score ---


def test_fib_gann_confluence_score_finds_confluence_fib_alone_misses():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    fib_levels = fgt.compute_fib_levels(swing_low=80.0, swing_high=100.0)
    gann_prices = fgt.gann_fan_prices(pivot, basis, bar_index=25)  # 2x1 == 100.0 here

    reference_price = gann_prices["2x1"] + 0.1
    fib_only = fgt.fib_confluence_score(fib_levels, reference_price, atr_value=1.0)
    fib_gann = fgt.fib_gann_confluence_score(fib_levels, gann_prices, reference_price, atr_value=1.0)
    assert fib_only == 0.0
    assert fib_gann > 0.5


def test_fib_gann_confluence_score_far_from_everything_is_zero():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    fib_levels = fgt.compute_fib_levels(swing_low=80.0, swing_high=100.0)
    gann_prices = fgt.gann_fan_prices(pivot, basis, bar_index=25)
    assert fgt.fib_gann_confluence_score(fib_levels, gann_prices, reference_price=1000.0, atr_value=1.0) == 0.0


def test_fib_gann_confluence_score_zero_atr_returns_zero_not_error():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    fib_levels = fgt.compute_fib_levels(swing_low=80.0, swing_high=100.0)
    gann_prices = fgt.gann_fan_prices(pivot, basis, bar_index=25)
    assert fgt.fib_gann_confluence_score(fib_levels, gann_prices, reference_price=90.0, atr_value=0.0) == 0.0


# --- confluence_across_timeframes ---


def test_confluence_across_timeframes_full_set():
    result = fgt.confluence_across_timeframes({"1w": 0.8, "1d": 0.6, "4h": 0.4, "1h": 0.2})
    expected = 100 * (0.8 * 0.4 + 0.6 * 0.3 + 0.4 * 0.2 + 0.2 * 0.1)
    assert result == pytest.approx(expected)


def test_confluence_across_timeframes_renormalizes_missing_timeframes():
    # Weekly/1h missing entirely -- must not be silently treated as zero.
    result = fgt.confluence_across_timeframes({"1d": 0.6, "4h": 0.4})
    expected = 100 * (0.6 * 0.3 + 0.4 * 0.2) / (0.3 + 0.2)
    assert result == pytest.approx(expected)


def test_confluence_across_timeframes_empty_input_returns_zero():
    assert fgt.confluence_across_timeframes({}) == 0.0


# --- ConfluenceWeights / score_confluence ---


def test_confluence_weights_must_sum_to_one():
    with pytest.raises(ValueError, match="must sum to 1.0"):
        fgt.ConfluenceWeights(
            swing_quality=0.5, fib_gann_confluence=0.5, regime_alignment=0.5, volume_confirmation=0.0, wick_rejection=0.0
        )


def test_score_confluence_defaults_regime_alignment_to_neutral():
    candles = [mk(i, 100, 101, 99, 100) for i in range(25)]
    swing = fgt.SwingPoint(index=20, ts=candles[20].ts, price=100, direction=fgt.SwingDirection.LOW, wick_rejection_score=0.7)
    score = fgt.score_confluence(swing, candles, fib_confluence=0.8, regime_alignment=None)
    weights = fgt.ConfluenceWeights()
    quality = fgt.swing_quality(swing, candles)
    vol_conf = min(1.0, fgt.volume_confirmation(swing, candles) / 2.0)
    expected = (
        weights.swing_quality * quality
        + weights.fib_gann_confluence * 0.8
        + weights.regime_alignment * 1.0  # neutral default
        + weights.volume_confirmation * vol_conf
        + weights.wick_rejection * 0.7
    )
    assert score == pytest.approx(expected)
