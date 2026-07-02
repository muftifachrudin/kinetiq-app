import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402
import market_structure as ms  # noqa: E402

UTC = datetime.timezone.utc


def sw(index: int, price: float, direction: fgt.SwingDirection) -> fgt.SwingPoint:
    ts = datetime.datetime(2026, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=index)
    return fgt.SwingPoint(index=index, ts=ts, price=price, direction=direction, wick_rejection_score=0.0)


UPTREND_SWINGS = [
    sw(0, 90, fgt.SwingDirection.HIGH),
    sw(1, 85, fgt.SwingDirection.LOW),
    sw(2, 95, fgt.SwingDirection.HIGH),
    sw(3, 88, fgt.SwingDirection.LOW),
]

DOWNTREND_SWINGS = [
    sw(0, 95, fgt.SwingDirection.HIGH),
    sw(1, 90, fgt.SwingDirection.LOW),
    sw(2, 92, fgt.SwingDirection.HIGH),
    sw(3, 85, fgt.SwingDirection.LOW),
]


# --- trend_bias ---


def test_trend_bias_higher_highs_higher_lows_is_uptrend():
    assert ms.trend_bias(UPTREND_SWINGS) is ms.TrendBias.UPTREND


def test_trend_bias_lower_highs_lower_lows_is_downtrend():
    assert ms.trend_bias(DOWNTREND_SWINGS) is ms.TrendBias.DOWNTREND


def test_trend_bias_mixed_signals_is_undefined():
    # higher high (90 -> 95) but lower low (85 -> 80) -- disagreeing signals
    swings = [
        sw(0, 90, fgt.SwingDirection.HIGH),
        sw(1, 85, fgt.SwingDirection.LOW),
        sw(2, 95, fgt.SwingDirection.HIGH),
        sw(3, 80, fgt.SwingDirection.LOW),
    ]
    assert ms.trend_bias(swings) is ms.TrendBias.UNDEFINED


def test_trend_bias_insufficient_swings_is_undefined():
    swings = [sw(0, 90, fgt.SwingDirection.HIGH), sw(1, 85, fgt.SwingDirection.LOW)]
    assert ms.trend_bias(swings) is ms.TrendBias.UNDEFINED


def test_trend_bias_empty_swings_is_undefined():
    assert ms.trend_bias([]) is ms.TrendBias.UNDEFINED


def test_trend_bias_uses_only_last_two_of_each_type():
    # first two highs/lows would say downtrend, but the *last* two say uptrend
    swings = [
        sw(0, 100, fgt.SwingDirection.HIGH),
        sw(1, 95, fgt.SwingDirection.LOW),
        sw(2, 90, fgt.SwingDirection.HIGH),  # lower high vs idx0
        sw(3, 85, fgt.SwingDirection.LOW),  # lower low vs idx1
        sw(4, 96, fgt.SwingDirection.HIGH),  # higher high vs idx2
        sw(5, 89, fgt.SwingDirection.LOW),  # higher low vs idx3
    ]
    assert ms.trend_bias(swings) is ms.TrendBias.UPTREND


# --- detect_structure_event ---


def test_detect_structure_event_bos_on_uptrend_continuation():
    event = ms.detect_structure_event(UPTREND_SWINGS, reference_price=97.0)
    assert event.event_type is ms.StructureEventType.BOS
    assert event.break_direction is ms.StructureBreakDirection.BULLISH
    assert event.trend_bias_before is ms.TrendBias.UPTREND
    assert event.broken_level == pytest.approx(95.0)


def test_detect_structure_event_choch_on_uptrend_reversal():
    event = ms.detect_structure_event(UPTREND_SWINGS, reference_price=86.0)
    assert event.event_type is ms.StructureEventType.CHOCH
    assert event.break_direction is ms.StructureBreakDirection.BEARISH
    assert event.broken_level == pytest.approx(88.0)


def test_detect_structure_event_bos_on_downtrend_continuation():
    event = ms.detect_structure_event(DOWNTREND_SWINGS, reference_price=83.0)
    assert event.event_type is ms.StructureEventType.BOS
    assert event.break_direction is ms.StructureBreakDirection.BEARISH


def test_detect_structure_event_choch_on_downtrend_reversal():
    event = ms.detect_structure_event(DOWNTREND_SWINGS, reference_price=93.0)
    assert event.event_type is ms.StructureEventType.CHOCH
    assert event.break_direction is ms.StructureBreakDirection.BULLISH


def test_detect_structure_event_none_when_price_still_inside_range():
    event = ms.detect_structure_event(UPTREND_SWINGS, reference_price=91.0)
    assert event is None


def test_detect_structure_event_undefined_trend_break_is_classified_as_choch():
    swings = [sw(0, 90, fgt.SwingDirection.HIGH), sw(1, 85, fgt.SwingDirection.LOW), sw(2, 88, fgt.SwingDirection.LOW)]
    event = ms.detect_structure_event(swings, reference_price=92.0)
    assert event.event_type is ms.StructureEventType.CHOCH
    assert event.trend_bias_before is ms.TrendBias.UNDEFINED


def test_detect_structure_event_none_without_both_a_high_and_a_low():
    swings = [sw(0, 90, fgt.SwingDirection.HIGH)]
    assert ms.detect_structure_event(swings, reference_price=100.0) is None


def test_detect_structure_event_empty_swings_returns_none():
    assert ms.detect_structure_event([], reference_price=100.0) is None


# --- structure_alignment_score ---


def test_structure_alignment_score_neutral_when_no_event():
    assert ms.structure_alignment_score(None, fgt.TradeDirection.LONG) == ms.STRUCTURE_ALIGNMENT_SCORE_NEUTRAL


def test_structure_alignment_score_aligned_bullish_break_with_long():
    event = ms.detect_structure_event(UPTREND_SWINGS, reference_price=97.0)  # bullish break
    assert ms.structure_alignment_score(event, fgt.TradeDirection.LONG) == ms.STRUCTURE_ALIGNMENT_SCORE_ALIGNED


def test_structure_alignment_score_opposed_bullish_break_with_short():
    event = ms.detect_structure_event(UPTREND_SWINGS, reference_price=97.0)  # bullish break
    assert ms.structure_alignment_score(event, fgt.TradeDirection.SHORT) == ms.STRUCTURE_ALIGNMENT_SCORE_OPPOSED


def test_structure_alignment_score_choch_can_align_with_a_new_direction_trade():
    # a bearish CHoCH (reversal signal) is exactly what a SHORT wants,
    # even though it's a "reversal" event, not a "continuation" one --
    # scoring must key off break direction, not the BOS/CHoCH label.
    event = ms.detect_structure_event(UPTREND_SWINGS, reference_price=86.0)  # bearish CHoCH
    assert event.event_type is ms.StructureEventType.CHOCH
    assert ms.structure_alignment_score(event, fgt.TradeDirection.SHORT) == ms.STRUCTURE_ALIGNMENT_SCORE_ALIGNED
    assert ms.structure_alignment_score(event, fgt.TradeDirection.LONG) == ms.STRUCTURE_ALIGNMENT_SCORE_OPPOSED
