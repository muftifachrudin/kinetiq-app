import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402
import post_stop_behavior as psb  # noqa: E402

UTC = datetime.timezone.utc
LONG = fgt.TradeDirection.LONG
SHORT = fgt.TradeDirection.SHORT


def mk(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(
        ts=datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=i), open=o, high=h, low=l, close=c, volume=v
    )


# --- classify_post_stop_behavior ---


def test_classify_rejects_empty_candles():
    with pytest.raises(ValueError, match="must not be empty"):
        psb.classify_post_stop_behavior([], 0, LONG, 100.0, 95.0, [])


def test_classify_rejects_non_positive_lookforward():
    candles = [mk(0, 100, 100, 100, 100), mk(1, 100, 100, 100, 100)]
    with pytest.raises(ValueError, match="must be positive"):
        psb.classify_post_stop_behavior(candles, 0, LONG, 100.0, 95.0, [4.0, 4.0], max_lookforward_bars=0)


def test_classify_long_retrace_to_entry():
    # LONG stopped out at bar 0 (SL=95), then closes back at/above
    # entry_price=100 on bar 2 -- "pulang ke rumah".
    candles = [mk(0, 95, 95.5, 94.5, 95)] + [mk(1, 96, 97, 95.5, 96.5), mk(2, 97, 100.5, 96.5, 100.2)]
    atr_series = [4.0, 4.0, 4.0]
    result = psb.classify_post_stop_behavior(candles, 0, LONG, entry_price=100.0, stop_loss=95.0, atr_series=atr_series)
    assert result.outcome is psb.PostStopOutcome.RETRACE_TO_ENTRY
    assert result.resolved_index == 2
    assert result.bars_to_resolution == 2
    assert result.censored is False


def test_classify_long_reversal_continuation():
    # LONG stopped out at bar 0 (SL=95, entry=100), then price keeps
    # falling well past SL (buffer 1.0*ATR=4.0 below 95 = 91) -- a real
    # reversal, "tujuan baru arah berlawanan".
    candles = [mk(0, 95, 95.5, 94.5, 95), mk(1, 94, 94.5, 89, 90)]
    atr_series = [4.0, 4.0]
    result = psb.classify_post_stop_behavior(candles, 0, LONG, entry_price=100.0, stop_loss=95.0, atr_series=atr_series)
    assert result.outcome is psb.PostStopOutcome.REVERSAL_CONTINUATION
    assert result.resolved_index == 1
    assert result.resolved_price == pytest.approx(90.0)


def test_classify_short_retrace_to_entry():
    candles = [mk(0, 105, 105.5, 104.5, 105), mk(1, 104, 104.5, 99.5, 100)]
    atr_series = [4.0, 4.0]
    result = psb.classify_post_stop_behavior(candles, 0, SHORT, entry_price=100.0, stop_loss=105.0, atr_series=atr_series)
    assert result.outcome is psb.PostStopOutcome.RETRACE_TO_ENTRY
    assert result.resolved_index == 1


def test_classify_short_reversal_continuation():
    candles = [mk(0, 105, 105.5, 104.5, 105), mk(1, 106, 111, 105.5, 110)]
    atr_series = [4.0, 4.0]
    result = psb.classify_post_stop_behavior(candles, 0, SHORT, entry_price=100.0, stop_loss=105.0, atr_series=atr_series)
    assert result.outcome is psb.PostStopOutcome.REVERSAL_CONTINUATION
    assert result.resolved_price == pytest.approx(110.0)


def test_classify_chop_when_neither_happens_within_window():
    # closes hover between entry(100) and SL(95) minus buffer -- neither
    # threshold crossed, plenty of data left (not censored).
    candles = [mk(0, 95, 95.5, 94.5, 95)] + [mk(i, 97, 97.5, 96.5, 97) for i in range(1, 15)]
    atr_series = [4.0] * 15
    result = psb.classify_post_stop_behavior(candles, 0, LONG, entry_price=100.0, stop_loss=95.0, atr_series=atr_series, max_lookforward_bars=10)
    assert result.outcome is psb.PostStopOutcome.CHOP
    assert result.censored is False  # had enough data, genuinely inconclusive


def test_classify_chop_and_censored_when_data_runs_out():
    candles = [mk(0, 95, 95.5, 94.5, 95), mk(1, 97, 97.5, 96.5, 97)]  # only 1 bar of forward data
    atr_series = [4.0, 4.0]
    result = psb.classify_post_stop_behavior(candles, 0, LONG, entry_price=100.0, stop_loss=95.0, atr_series=atr_series, max_lookforward_bars=10)
    assert result.outcome is psb.PostStopOutcome.CHOP
    assert result.censored is True


def test_classify_skips_bars_with_no_atr_for_continuation_check():
    # ATR is None on the only forward bar -- continuation can't be
    # evaluated there, and the close doesn't retrace either, so CHOP.
    candles = [mk(0, 95, 95.5, 94.5, 95), mk(1, 90, 90.5, 89.5, 90)]
    atr_series = [None, None]
    result = psb.classify_post_stop_behavior(candles, 0, LONG, entry_price=100.0, stop_loss=95.0, atr_series=atr_series, max_lookforward_bars=1)
    assert result.outcome is psb.PostStopOutcome.CHOP


def test_classify_retrace_checked_before_continuation_would_matter_chronologically():
    # bar 1 retraces to entry; bar 2 would have continued further down --
    # must resolve at bar 1 (first bar where a threshold is crossed),
    # never look past it.
    candles = [mk(0, 95, 95.5, 94.5, 95), mk(1, 100, 100.5, 99.5, 100.5), mk(2, 90, 90.5, 89.5, 90)]
    atr_series = [4.0, 4.0, 4.0]
    result = psb.classify_post_stop_behavior(candles, 0, LONG, entry_price=100.0, stop_loss=95.0, atr_series=atr_series)
    assert result.outcome is psb.PostStopOutcome.RETRACE_TO_ENTRY
    assert result.resolved_index == 1


# --- build_post_stop_profile / predict_post_stop_outcome ---


def test_build_post_stop_profile_rejects_empty():
    with pytest.raises(ValueError, match="must not be empty"):
        psb.build_post_stop_profile([])


def test_predict_post_stop_outcome_no_historical_basis_returns_empty():
    profile = psb.build_post_stop_profile([psb.PostStopSample(psb.PostStopOutcome.CHOP, LONG, censored=False)])
    estimate = psb.predict_post_stop_outcome(profile, direction=SHORT)
    assert estimate.sample_count == 0
    assert estimate.outcome_probabilities == {}


def test_predict_post_stop_outcome_computes_empirical_probabilities():
    samples = [
        psb.PostStopSample(psb.PostStopOutcome.RETRACE_TO_ENTRY, LONG, censored=False),
        psb.PostStopSample(psb.PostStopOutcome.RETRACE_TO_ENTRY, LONG, censored=False),
        psb.PostStopSample(psb.PostStopOutcome.REVERSAL_CONTINUATION, LONG, censored=False),
        psb.PostStopSample(psb.PostStopOutcome.CHOP, LONG, censored=False),
    ]
    profile = psb.build_post_stop_profile(samples)
    estimate = psb.predict_post_stop_outcome(profile, direction=LONG)
    assert estimate.sample_count == 4
    assert estimate.outcome_probabilities[psb.PostStopOutcome.RETRACE_TO_ENTRY] == pytest.approx(0.5)
    assert estimate.outcome_probabilities[psb.PostStopOutcome.REVERSAL_CONTINUATION] == pytest.approx(0.25)
    assert estimate.outcome_probabilities[psb.PostStopOutcome.CHOP] == pytest.approx(0.25)
    assert sum(estimate.outcome_probabilities.values()) == pytest.approx(1.0)


def test_predict_post_stop_outcome_excludes_censored_samples():
    samples = [
        psb.PostStopSample(psb.PostStopOutcome.RETRACE_TO_ENTRY, LONG, censored=False),
        psb.PostStopSample(psb.PostStopOutcome.CHOP, LONG, censored=True),
    ]
    profile = psb.build_post_stop_profile(samples)
    estimate = psb.predict_post_stop_outcome(profile, direction=LONG)
    assert estimate.sample_count == 1
    assert estimate.outcome_probabilities[psb.PostStopOutcome.RETRACE_TO_ENTRY] == pytest.approx(1.0)


def test_predict_post_stop_outcome_direction_isolation():
    samples = [
        psb.PostStopSample(psb.PostStopOutcome.RETRACE_TO_ENTRY, LONG, censored=False),
        psb.PostStopSample(psb.PostStopOutcome.REVERSAL_CONTINUATION, SHORT, censored=False),
    ]
    profile = psb.build_post_stop_profile(samples)
    long_estimate = psb.predict_post_stop_outcome(profile, direction=LONG)
    assert long_estimate.sample_count == 1
    assert long_estimate.outcome_probabilities == {psb.PostStopOutcome.RETRACE_TO_ENTRY: 1.0}
