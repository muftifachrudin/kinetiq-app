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
    # 0% = swing_low, 100% = swing_high, extensions continue ABOVE
    # swing_high (verified against real TradingView coordinates below --
    # this is NOT the "swing_high - level*leg" formula this function used
    # before 3 Juli 2026).
    levels = fgt.compute_fib_levels(swing_low=80.0, swing_high=100.0)
    assert levels["retracement"][0.618] == pytest.approx(80 + 0.618 * 20)
    assert levels["retracement"][0.886] == pytest.approx(80 + 0.886 * 20)
    assert levels["extension"][1.618] == pytest.approx(80 + 1.618 * 20)
    assert set(levels["retracement"]) == set(fgt.DEFAULT_FIB_RETRACEMENT_LEVELS)
    assert set(levels["extension"]) == set(fgt.DEFAULT_FIB_EXTENSION_LEVELS)


def test_compute_fib_levels_rejects_inverted_swing():
    with pytest.raises(ValueError, match="must be greater than"):
        fgt.compute_fib_levels(swing_low=100.0, swing_high=80.0)


def test_compute_fib_levels_accepts_custom_levels():
    levels = fgt.compute_fib_levels(swing_low=0.0, swing_high=100.0, retracement_levels=(0.5,), extension_levels=())
    assert levels["retracement"] == {0.5: 50.0}
    assert levels["extension"] == {}


def test_compute_fib_levels_matches_real_tradingview_coordinates():
    # design brief Section 2a verification (3 Juli 2026): exact (price,
    # bar) coordinates from the founder's real Fib Retracement tool
    # (BTCUSDT 1h) -- point #1 = 60919.9 @ bar 160, point #2 = 58029.2 @
    # bar 328 -- plus every level price read straight off the chart
    # labels. A least-squares fit of these 9 points against `swing_low +
    # level*leg` gave R^2 = 1.000000 (tiny per-level residuals are
    # decimal-rounding in the displayed coordinates, not formula error).
    levels = fgt.compute_fib_levels(swing_low=58029.2, swing_high=60919.9)
    observed = {
        0.382: 59135.5,
        0.5: 59477.2,
        0.618: 59819.0,
        0.786: 60305.5,
        0.886: 60595.1,
        1.13: 61301.7,
        1.272: 61712.9,
        1.414: 62124.2,
        1.618: 62715.0,
    }
    for level, expected_price in observed.items():
        pool = levels["retracement"] if level < 1.0 else levels["extension"]
        assert pool[level] == pytest.approx(expected_price, abs=10.0)


# --- Gann Fan ---


def sw(index: int, price: float, direction: fgt.SwingDirection) -> fgt.SwingPoint:
    return fgt.SwingPoint(
        index=index, ts=mk(index, price, price, price, price).ts, price=price, direction=direction, wick_rejection_score=0.0
    )


def test_gann_base_rate():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    assert fgt.gann_base_rate(pivot, basis) == pytest.approx(2.0)  # 20 price / 10 bars


def test_gann_base_rate_rejects_shared_index():
    basis = sw(20, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)  # same index as basis
    with pytest.raises(ValueError, match="must not share the same index"):
        fgt.gann_base_rate(pivot, basis)


def test_gann_base_rate_accepts_basis_leg_start_after_pivot():
    # design brief Section 2c verification (3 Juli 2026): the founder's
    # manual TradingView drawings anchor the fan's origin at an OLDER
    # swing and pick a LATER point just to define slope -- the reverse
    # chronological order from live/backtest usage (detect_swings()
    # always has the most-recent swing as pivot). Both must produce the
    # same rate for the same two points, order-independent.
    pivot = sw(10, 100.0, fgt.SwingDirection.HIGH)  # earlier, is the origin
    basis = sw(20, 80.0, fgt.SwingDirection.LOW)  # later, defines the slope
    assert fgt.gann_base_rate(pivot, basis) == pytest.approx(2.0)  # same 20 price / 10 bars


def test_gann_base_rate_real_tradingview_coordinates_uptrend():
    # exact (price, bar) coordinates read from the founder's own
    # TradingView Gann Fan Coordinates panel, not visual estimation --
    # origin (LOW) is chronologically BEFORE the slope-defining point.
    pivot = sw(127, 58005.0, fgt.SwingDirection.LOW)
    basis = sw(177, 60908.9, fgt.SwingDirection.HIGH)
    assert fgt.gann_base_rate(pivot, basis) == pytest.approx(58.078, abs=0.001)


def test_gann_base_rate_real_tradingview_coordinates_downtrend():
    # same verification, downtrend case -- origin (HIGH) also
    # chronologically BEFORE the slope-defining point.
    pivot = sw(197, 67284.8, fgt.SwingDirection.HIGH)
    basis = sw(214, 62233.3, fgt.SwingDirection.LOW)
    assert fgt.gann_base_rate(pivot, basis) == pytest.approx(297.1471, abs=0.001)


def test_gann_base_rate_real_tradingview_coordinates_different_instrument():
    # third real verification (SOLUSDT, 1h -- BTC's two examples above are
    # both perpetuals at a completely different price scale, ~58k-67k vs
    # ~64-74 here) -- confirms the formula is genuinely price-scale
    # adaptive per the design brief, not just coincidentally right for BTC.
    pivot = sw(127, 64.03, fgt.SwingDirection.LOW)
    basis = sw(157, 73.84, fgt.SwingDirection.HIGH)
    assert fgt.gann_base_rate(pivot, basis) == pytest.approx(0.327, abs=0.001)


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


def test_gann_fan_prices_origin_before_slope_point_matches_real_tradingview_coordinates():
    # end-to-end version of the two real-data unit tests above: the fan's
    # 1x1 line at the slope-defining point's own bar must land exactly on
    # that point's own price, regardless of which of the two points is
    # chronologically first.
    pivot = sw(127, 58005.0, fgt.SwingDirection.LOW)
    basis = sw(177, 60908.9, fgt.SwingDirection.HIGH)
    prices = fgt.gann_fan_prices(pivot, basis, bar_index=177)
    assert prices["1x1"] == pytest.approx(60908.9, abs=0.01)

    pivot2 = sw(197, 67284.8, fgt.SwingDirection.HIGH)
    basis2 = sw(214, 62233.3, fgt.SwingDirection.LOW)
    prices2 = fgt.gann_fan_prices(pivot2, basis2, bar_index=214)
    assert prices2["1x1"] == pytest.approx(62233.3, abs=0.01)


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


# --- trade_direction_from_pivot / compute_stop_loss ---


def test_trade_direction_from_pivot_low_is_long():
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    assert fgt.trade_direction_from_pivot(pivot) is fgt.TradeDirection.LONG


def test_trade_direction_from_pivot_high_is_short():
    pivot = sw(20, 100.0, fgt.SwingDirection.HIGH)
    assert fgt.trade_direction_from_pivot(pivot) is fgt.TradeDirection.SHORT


def test_compute_stop_loss_long_places_sl_below_pivot():
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    sl = fgt.compute_stop_loss(pivot, atr_value=4.0, atr_buffer_multiplier=0.5)
    assert sl == pytest.approx(80.0 - 0.5 * 4.0)


def test_compute_stop_loss_short_places_sl_above_pivot():
    pivot = sw(20, 100.0, fgt.SwingDirection.HIGH)
    sl = fgt.compute_stop_loss(pivot, atr_value=4.0, atr_buffer_multiplier=0.5)
    assert sl == pytest.approx(100.0 + 0.5 * 4.0)


def test_compute_stop_loss_rejects_non_positive_atr():
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    with pytest.raises(ValueError, match="must be positive"):
        fgt.compute_stop_loss(pivot, atr_value=0.0)


# --- compute_take_profit_levels ---


def test_compute_take_profit_levels_long_projects_above_swing_high_and_filters_by_gann_confluence():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    gann_prices = fgt.gann_fan_prices(pivot, basis, bar_index=30)  # includes 2x1 == 120.0 here
    tps = fgt.compute_take_profit_levels(pivot, basis, gann_prices, atr_value=4.0)
    assert tps == (120.0,)
    assert all(p > 100.0 for p in tps)


def test_compute_take_profit_levels_long_matches_compute_fib_levels_extension_formula():
    # since the 3 Juli 2026 real-chart fix, compute_fib_levels' extension
    # formula (0%=low, 100%=high, extensions above high) is now
    # mathematically identical to this function's LONG branch -- verify
    # that equivalence explicitly so a future change to either doesn't
    # silently diverge them again.
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    gann_prices = fgt.gann_fan_prices(pivot, basis, bar_index=30)
    tps = fgt.compute_take_profit_levels(pivot, basis, gann_prices, atr_value=4.0)
    fib_levels = fgt.compute_fib_levels(swing_low=80.0, swing_high=100.0)
    assert tps == (120.0,)
    assert tps[0] == pytest.approx(fib_levels["extension"][2.0])


def test_compute_take_profit_levels_short_projects_below_swing_low():
    # SHORT branch is a mirror-image assumption for symmetry -- NOT yet
    # verified against a real SHORT-oriented TradingView Fib drawing (see
    # compute_take_profit_levels' docstring). This only locks in its
    # current, documented behavior, not that the behavior is confirmed
    # correct.
    basis = sw(10, 80.0, fgt.SwingDirection.LOW)
    pivot = sw(20, 100.0, fgt.SwingDirection.HIGH)
    gann_prices = fgt.gann_fan_prices(pivot, basis, bar_index=30)  # includes 2x1 == 60.0 here
    tps = fgt.compute_take_profit_levels(pivot, basis, gann_prices, atr_value=4.0)
    assert tps == (60.0,)
    assert all(p < 80.0 for p in tps)


def test_compute_take_profit_levels_no_gann_confluence_returns_empty_tuple():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    no_confluence_gann = {"far": 99999.0}
    tps = fgt.compute_take_profit_levels(pivot, basis, no_confluence_gann, atr_value=4.0)
    assert tps == ()


def test_compute_take_profit_levels_orders_nearest_first():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    # A huge ATR band makes every extension level Gann-confluent (each is
    # within 0.5x ATR of some Gann angle price) -- so ordering is driven
    # purely by extension ratio ascending, not by which happen to be
    # confluent.
    gann_prices = fgt.gann_fan_prices(pivot, basis, bar_index=30)
    tps = fgt.compute_take_profit_levels(pivot, basis, gann_prices, atr_value=1000.0)
    assert list(tps) == sorted(tps)


def test_compute_take_profit_levels_rejects_zero_leg():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 100.0, fgt.SwingDirection.LOW)
    with pytest.raises(ValueError, match="different prices"):
        fgt.compute_take_profit_levels(pivot, basis, {}, atr_value=4.0)


# --- build_exit_plan / passes_risk_reward_gate ---


def test_build_exit_plan_computes_risk_reward_ratio():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    gann_prices = fgt.gann_fan_prices(pivot, basis, bar_index=30)
    plan = fgt.build_exit_plan(pivot, basis, entry_price=81.0, atr_value=4.0, gann_prices=gann_prices)
    assert plan.direction is fgt.TradeDirection.LONG
    assert plan.stop_loss == pytest.approx(80.0 - fgt.DEFAULT_SL_ATR_BUFFER_MULTIPLIER * 4.0)
    assert plan.take_profits == (120.0,)
    expected_rr = abs(120.0 - 81.0) / abs(81.0 - plan.stop_loss)
    assert plan.risk_reward_ratio == pytest.approx(expected_rr)


def test_build_exit_plan_risk_reward_ratio_is_none_when_no_take_profit_found():
    basis = sw(10, 100.0, fgt.SwingDirection.HIGH)
    pivot = sw(20, 80.0, fgt.SwingDirection.LOW)
    plan = fgt.build_exit_plan(pivot, basis, entry_price=81.0, atr_value=4.0, gann_prices={"far": 99999.0})
    assert plan.take_profits == ()
    assert plan.risk_reward_ratio is None


def test_passes_risk_reward_gate_true_when_ratio_meets_threshold():
    plan = fgt.ExitPlan(
        direction=fgt.TradeDirection.LONG, entry_price=81.0, stop_loss=78.5, take_profits=(120.0,), risk_reward_ratio=15.6
    )
    assert fgt.passes_risk_reward_gate(plan, min_rr_threshold=1.5) is True


def test_passes_risk_reward_gate_false_when_ratio_below_threshold():
    plan = fgt.ExitPlan(
        direction=fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=90.0, take_profits=(105.0,), risk_reward_ratio=0.5
    )
    assert fgt.passes_risk_reward_gate(plan, min_rr_threshold=1.5) is False


def test_passes_risk_reward_gate_false_when_no_take_profit_found():
    plan = fgt.ExitPlan(direction=fgt.TradeDirection.LONG, entry_price=81.0, stop_loss=78.5, take_profits=(), risk_reward_ratio=None)
    assert fgt.passes_risk_reward_gate(plan) is False


# --- label_triple_barrier ---

LONG_PLAN = fgt.ExitPlan(direction=fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=90.0, take_profits=(120.0,), risk_reward_ratio=2.0)
SHORT_PLAN = fgt.ExitPlan(direction=fgt.TradeDirection.SHORT, entry_price=100.0, stop_loss=110.0, take_profits=(80.0,), risk_reward_ratio=2.0)


def test_label_triple_barrier_long_take_profit_hit_first():
    candles = [mk(0, 100, 105, 95, 102), mk(1, 102, 125, 101, 124), mk(2, 124, 130, 120, 125)]
    label = fgt.label_triple_barrier(LONG_PLAN, candles, max_holding_bars=3)
    assert label.outcome is fgt.BarrierOutcome.TAKE_PROFIT
    assert label.exit_price == pytest.approx(120.0)
    assert label.bars_held == 2
    assert label.return_pct == pytest.approx(0.2)
    assert label.censored is False


def test_label_triple_barrier_long_stop_loss_hit_first():
    candles = [mk(0, 100, 105, 95, 102), mk(1, 102, 103, 85, 90), mk(2, 90, 95, 85, 92)]
    label = fgt.label_triple_barrier(LONG_PLAN, candles, max_holding_bars=3)
    assert label.outcome is fgt.BarrierOutcome.STOP_LOSS
    assert label.exit_price == pytest.approx(90.0)
    assert label.bars_held == 2
    assert label.return_pct == pytest.approx(-0.1)


def test_label_triple_barrier_long_double_touch_scores_as_stop_loss():
    # brief's explicit worst-case rule: both TP (120) and SL (90) fall
    # within this single candle's high-low range -- can't tell which was
    # touched first, so it must be scored as the loss, not the win.
    candles = [mk(0, 100, 125, 85, 100)]
    label = fgt.label_triple_barrier(LONG_PLAN, candles, max_holding_bars=3)
    assert label.outcome is fgt.BarrierOutcome.STOP_LOSS
    assert label.exit_price == pytest.approx(90.0)
    assert label.bars_held == 1


def test_label_triple_barrier_short_take_profit_hit_first():
    candles = [mk(0, 100, 102, 98, 99), mk(1, 99, 95, 75, 80)]
    label = fgt.label_triple_barrier(SHORT_PLAN, candles, max_holding_bars=3)
    assert label.outcome is fgt.BarrierOutcome.TAKE_PROFIT
    assert label.exit_price == pytest.approx(80.0)
    assert label.return_pct == pytest.approx(0.2)


def test_label_triple_barrier_short_stop_loss_hit_first():
    candles = [mk(0, 100, 102, 98, 99), mk(1, 99, 112, 95, 105)]
    label = fgt.label_triple_barrier(SHORT_PLAN, candles, max_holding_bars=3)
    assert label.outcome is fgt.BarrierOutcome.STOP_LOSS
    assert label.exit_price == pytest.approx(110.0)
    assert label.return_pct == pytest.approx(-0.1)


def test_label_triple_barrier_short_double_touch_scores_as_stop_loss():
    candles = [mk(0, 100, 112, 75, 100)]
    label = fgt.label_triple_barrier(SHORT_PLAN, candles, max_holding_bars=3)
    assert label.outcome is fgt.BarrierOutcome.STOP_LOSS
    assert label.exit_price == pytest.approx(110.0)


def test_label_triple_barrier_timeout_not_censored_when_more_data_was_available():
    candles = [mk(i, 100, 105, 95, 101) for i in range(5)]  # neither barrier ever touched
    label = fgt.label_triple_barrier(LONG_PLAN, candles, max_holding_bars=3)
    assert label.outcome is fgt.BarrierOutcome.TIMEOUT
    assert label.exit_price == pytest.approx(101.0)  # close of the 3rd (last window) candle
    assert label.bars_held == 3
    assert label.censored is False


def test_label_triple_barrier_timeout_censored_when_data_ran_out_early():
    candles = [mk(i, 100, 105, 95, 101) for i in range(2)]  # only 2 candles, window wants 5
    label = fgt.label_triple_barrier(LONG_PLAN, candles, max_holding_bars=5)
    assert label.outcome is fgt.BarrierOutcome.TIMEOUT
    assert label.bars_held == 2
    assert label.censored is True


def test_label_triple_barrier_rejects_empty_candles():
    with pytest.raises(ValueError, match="must not be empty"):
        fgt.label_triple_barrier(LONG_PLAN, [], max_holding_bars=3)


def test_label_triple_barrier_rejects_non_positive_max_holding_bars():
    candles = [mk(0, 100, 105, 95, 101)]
    with pytest.raises(ValueError, match="must be positive"):
        fgt.label_triple_barrier(LONG_PLAN, candles, max_holding_bars=0)


def test_label_triple_barrier_rejects_exit_plan_without_take_profit():
    candles = [mk(0, 100, 105, 95, 101)]
    plan = fgt.ExitPlan(direction=fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=90.0, take_profits=(), risk_reward_ratio=None)
    with pytest.raises(ValueError, match="no take_profits"):
        fgt.label_triple_barrier(plan, candles, max_holding_bars=3)


def test_barrier_outcome_is_directly_usable_as_int_label():
    assert int(fgt.BarrierOutcome.TAKE_PROFIT) == 1
    assert int(fgt.BarrierOutcome.STOP_LOSS) == -1
    assert int(fgt.BarrierOutcome.TIMEOUT) == 0
