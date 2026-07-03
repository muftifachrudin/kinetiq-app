import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402
import htf_bias as hb  # noqa: E402
import market_structure as ms  # noqa: E402

UTC = datetime.timezone.utc


def mk(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(
        ts=datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=i), open=o, high=h, low=l, close=c, volume=v
    )


def hourly_series(n: int, start_price: float = 100.0) -> list[fgt.Candle]:
    """n contiguous 1h candles, flat OHLC, distinct volumes so aggregation
    (sum) is checkable -- not meant to produce swings, just clean buckets."""
    return [mk(i, start_price, start_price + 1, start_price - 1, start_price, v=float(i + 1)) for i in range(n)]


# --- resample_candles ---


def test_resample_candles_rejects_unsupported_timeframe():
    with pytest.raises(ValueError, match="unsupported target_timeframe"):
        hb.resample_candles(hourly_series(10), "1h")


def test_resample_candles_empty_input_returns_empty():
    assert hb.resample_candles([], "4h") == []


def test_resample_candles_4h_aggregates_ohlcv_correctly():
    # candle 0 opens the first UTC day at 00:00, so hours 0-3 are one clean
    # 4h bucket -- open=candle0.open, close=candle3.close, high/low the
    # bucket extremes, volume summed.
    candles = [
        mk(0, 100, 105, 99, 101, v=10),
        mk(1, 101, 103, 98, 102, v=20),
        mk(2, 102, 110, 100, 103, v=30),
        mk(3, 103, 104, 95, 96, v=40),
        mk(4, 96, 97, 90, 92, v=50),  # start of the next bucket
        mk(5, 92, 93, 91, 92, v=60),
        mk(6, 92, 94, 89, 90, v=70),
        mk(7, 90, 91, 88, 89, v=80),  # closes the second bucket
    ]
    resampled = hb.resample_candles(candles, "4h")
    assert len(resampled) == 2
    first = resampled[0]
    assert first.ts == candles[0].ts
    assert first.open == 100
    assert first.close == 96
    assert first.high == 110
    assert first.low == 95
    assert first.volume == 10 + 20 + 30 + 40


def test_resample_candles_1d_calendar_aligned_not_anchored_to_first_candle():
    # start mid-day (hour 5) -- the first bucket must still be truncated to
    # that day's UTC midnight, not anchored to hour 5.
    candles = hourly_series(48, start_price=100.0)
    shifted = [
        fgt.Candle(ts=c.ts + datetime.timedelta(hours=5), open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume)
        for c in candles
    ]
    resampled = hb.resample_candles(shifted, "1d")
    for r in resampled:
        assert r.ts.hour == 0 and r.ts.minute == 0 and r.ts.second == 0


def test_resample_candles_drops_incomplete_trailing_bucket():
    # exactly 4 candles for one clean 4h bucket, then 2 more candles that
    # start a second bucket but don't complete it -- the second, partial
    # bucket must NOT appear (anti-lookahead: a bucket that hasn't closed
    # yet must never be readable as if it had).
    candles = [mk(i, 100, 101, 99, 100, v=1) for i in range(6)]
    resampled = hb.resample_candles(candles, "4h")
    assert len(resampled) == 1
    assert resampled[0].ts == candles[0].ts


def test_resample_candles_respects_as_of_cutoff():
    candles = [mk(i, 100, 101, 99, 100, v=1) for i in range(12)]
    # only the first bucket's hours (0-3) are visible as of candle 3's ts
    resampled = hb.resample_candles(candles, "4h", as_of=candles[3].ts)
    assert len(resampled) == 1
    # a cutoff mid-bucket (candle 5, inside the second 4h bucket) must not
    # complete that second bucket either
    resampled_mid = hb.resample_candles(candles, "4h", as_of=candles[5].ts)
    assert len(resampled_mid) == 1


def test_resample_candles_as_of_rejects_naive_datetime():
    candles = hourly_series(10)
    with pytest.raises(ValueError, match="timezone-aware"):
        hb.resample_candles(candles, "4h", as_of=datetime.datetime(2024, 1, 1))


# --- compute_bias ---


def test_compute_bias_undefined_when_insufficient_swings():
    # flat series -- no swings at all on any timeframe
    candles = [mk(i, 100, 100.5, 99.5, 100, v=1) for i in range(200)]
    assert hb.compute_bias(candles, "1d") is ms.TrendBias.UNDEFINED
    assert hb.compute_bias(candles, "4h") is ms.TrendBias.UNDEFINED


def test_compute_bias_rejects_unsupported_timeframe():
    with pytest.raises(ValueError, match="unsupported target_timeframe"):
        hb.compute_bias(hourly_series(10), "1h")


# --- htf_alignment_score ---


def test_bias_alignment_is_public_and_matches_aligned_opposed_neutral():
    # public (Fase 3, docs/sonnet5-implementation-roadmap.md): any OTHER
    # bias source (e.g. sma_trend_bias()) needs the same 0-1 mapping
    # htf_alignment_score() uses internally, without duplicating it.
    assert hb.bias_alignment(fgt.TradeDirection.LONG, ms.TrendBias.UPTREND) == hb.HTF_ALIGNMENT_SCORE_ALIGNED
    assert hb.bias_alignment(fgt.TradeDirection.LONG, ms.TrendBias.DOWNTREND) == hb.HTF_ALIGNMENT_SCORE_OPPOSED
    assert hb.bias_alignment(fgt.TradeDirection.LONG, ms.TrendBias.UNDEFINED) == hb.HTF_ALIGNMENT_SCORE_NEUTRAL
    assert hb.bias_alignment(fgt.TradeDirection.SHORT, ms.TrendBias.DOWNTREND) == hb.HTF_ALIGNMENT_SCORE_ALIGNED


def test_htf_alignment_score_full_agreement_returns_aligned():
    biases = {"1d": ms.TrendBias.UPTREND, "4h": ms.TrendBias.UPTREND}
    score = hb.htf_alignment_score(fgt.TradeDirection.LONG, biases)
    assert score == pytest.approx(hb.HTF_ALIGNMENT_SCORE_ALIGNED)


def test_htf_alignment_score_full_disagreement_returns_opposed():
    biases = {"1d": ms.TrendBias.DOWNTREND, "4h": ms.TrendBias.DOWNTREND}
    score = hb.htf_alignment_score(fgt.TradeDirection.LONG, biases)
    assert score == pytest.approx(hb.HTF_ALIGNMENT_SCORE_OPPOSED)


def test_htf_alignment_score_mixed_biases_weighted_average():
    biases = {"1d": ms.TrendBias.UPTREND, "4h": ms.TrendBias.DOWNTREND}
    weights = {"1d": 0.3, "4h": 0.2}
    score = hb.htf_alignment_score(fgt.TradeDirection.LONG, biases, weights=weights)
    expected = (hb.HTF_ALIGNMENT_SCORE_ALIGNED * 0.3 + hb.HTF_ALIGNMENT_SCORE_OPPOSED * 0.2) / 0.5
    assert score == pytest.approx(expected)


def test_htf_alignment_score_renormalizes_missing_timeframes():
    # "1w" is in DEFAULT_HTF_TIMEFRAME_WEIGHTS but absent from biases --
    # must not be silently treated as opposed/zero.
    biases = {"1d": ms.TrendBias.UPTREND}
    score = hb.htf_alignment_score(fgt.TradeDirection.LONG, biases)
    assert score == pytest.approx(hb.HTF_ALIGNMENT_SCORE_ALIGNED)


def test_htf_alignment_score_no_timeframes_present_returns_neutral():
    assert hb.htf_alignment_score(fgt.TradeDirection.LONG, {}) == pytest.approx(hb.HTF_ALIGNMENT_SCORE_NEUTRAL)


def test_htf_alignment_score_undefined_bias_counts_as_neutral():
    biases = {"1d": ms.TrendBias.UNDEFINED, "4h": ms.TrendBias.UPTREND}
    weights = {"1d": 0.5, "4h": 0.5}
    score = hb.htf_alignment_score(fgt.TradeDirection.LONG, biases, weights=weights)
    expected = (hb.HTF_ALIGNMENT_SCORE_NEUTRAL * 0.5 + hb.HTF_ALIGNMENT_SCORE_ALIGNED * 0.5) / 1.0
    assert score == pytest.approx(expected)


def test_htf_alignment_score_short_direction_mirrors_long():
    biases = {"1d": ms.TrendBias.DOWNTREND, "4h": ms.TrendBias.DOWNTREND}
    score = hb.htf_alignment_score(fgt.TradeDirection.SHORT, biases)
    assert score == pytest.approx(hb.HTF_ALIGNMENT_SCORE_ALIGNED)


# --- sma_trend_bias ---


def test_sma_trend_bias_undefined_with_insufficient_candles():
    candles = hourly_series(50)
    assert hb.sma_trend_bias(candles, period=200) is ms.TrendBias.UNDEFINED


def test_sma_trend_bias_uptrend_when_close_above_sma():
    candles = [mk(i, 100, 101, 99, 100, v=1) for i in range(199)] + [mk(199, 100, 120, 100, 120, v=1)]
    assert hb.sma_trend_bias(candles, period=200) is ms.TrendBias.UPTREND


def test_sma_trend_bias_downtrend_when_close_below_sma():
    candles = [mk(i, 100, 101, 99, 100, v=1) for i in range(199)] + [mk(199, 100, 100, 80, 80, v=1)]
    assert hb.sma_trend_bias(candles, period=200) is ms.TrendBias.DOWNTREND


def test_sma_trend_bias_undefined_when_close_equals_sma():
    candles = [mk(i, 100, 101, 99, 100, v=1) for i in range(200)]
    assert hb.sma_trend_bias(candles, period=200) is ms.TrendBias.UNDEFINED
