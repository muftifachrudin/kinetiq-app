import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402
import level_strength as ls  # noqa: E402

UTC = datetime.timezone.utc


def mk(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(
        ts=datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=i), open=o, high=h, low=l, close=c, volume=v
    )


def touch(
    index: int,
    outcome: ls.TouchOutcome = ls.TouchOutcome.BOUNCE,
    prior_touch_count: int = 0,
    approach: ls.ApproachDirection = ls.ApproachDirection.FROM_ABOVE,
) -> ls.LevelTouch:
    return ls.LevelTouch(
        level_key="x",
        level_price=100.0,
        touch_index=index,
        touch_ts=mk(index, 100, 100, 100, 100).ts,
        approach=approach,
        outcome=outcome,
        resolved_index=index + 1,
        prior_touch_count=prior_touch_count,
        censored=False,
    )


# --- detect_level_touches ---


def test_detect_level_touches_bounce_from_above():
    # approached from above (open >= level), then closes back above the
    # buffer -- level held as support.
    candles = [mk(0, 105, 106, 99, 101), mk(1, 101, 103, 100.5, 102.5)]
    atr_series = [4.0, 4.0]
    touches = ls.detect_level_touches(candles, lambda i: 100.0, "x", atr_series, max_resolution_bars=5)
    assert len(touches) == 1
    assert touches[0].outcome is ls.TouchOutcome.BOUNCE
    assert touches[0].approach is ls.ApproachDirection.FROM_ABOVE
    assert touches[0].resolved_index == 1
    assert touches[0].censored is False


def test_detect_level_touches_break_from_above():
    candles = [mk(0, 105, 106, 99, 101), mk(1, 101, 101.5, 96, 97)]
    atr_series = [4.0, 4.0]
    touches = ls.detect_level_touches(candles, lambda i: 100.0, "x", atr_series, max_resolution_bars=5)
    assert touches[0].outcome is ls.TouchOutcome.BREAK


def test_detect_level_touches_bounce_from_below():
    # approached from below (open < level), closes back below the buffer.
    candles = [mk(0, 95, 101, 94, 97), mk(1, 97, 97.5, 95, 96)]
    atr_series = [4.0, 4.0]
    touches = ls.detect_level_touches(candles, lambda i: 100.0, "x", atr_series, max_resolution_bars=5)
    assert touches[0].approach is ls.ApproachDirection.FROM_BELOW
    assert touches[0].outcome is ls.TouchOutcome.BOUNCE


def test_detect_level_touches_break_from_below():
    candles = [mk(0, 95, 101, 94, 97), mk(1, 97, 104, 96, 103)]
    atr_series = [4.0, 4.0]
    touches = ls.detect_level_touches(candles, lambda i: 100.0, "x", atr_series, max_resolution_bars=5)
    assert touches[0].outcome is ls.TouchOutcome.BREAK


def test_detect_level_touches_censored_when_ambiguous_within_window():
    # touches, but never decisively closes beyond the buffer either way
    # within the resolution window.
    candles = [mk(0, 105, 106, 99, 101)] + [mk(i, 100.1, 100.3, 99.9, 100.1) for i in range(1, 6)]
    atr_series = [4.0] * 6
    touches = ls.detect_level_touches(candles, lambda i: 100.0, "x", atr_series, max_resolution_bars=5)
    assert touches[0].outcome is ls.TouchOutcome.CENSORED
    assert touches[0].censored is False  # had enough data, genuinely inconclusive -- not right-censored


def test_detect_level_touches_censored_and_flagged_when_data_runs_out():
    candles = [mk(0, 105, 106, 99, 101)]  # touch, then series just ends
    atr_series = [4.0]
    touches = ls.detect_level_touches(candles, lambda i: 100.0, "x", atr_series, max_resolution_bars=5)
    assert touches[0].outcome is ls.TouchOutcome.CENSORED
    assert touches[0].censored is True


def test_detect_level_touches_no_touch_returns_empty():
    candles = [mk(0, 200, 201, 199, 200)]
    atr_series = [4.0]
    touches = ls.detect_level_touches(candles, lambda i: 100.0, "x", atr_series)
    assert touches == []


def test_detect_level_touches_skips_bars_with_no_atr():
    candles = [mk(0, 105, 106, 99, 101)]
    atr_series = [None]
    touches = ls.detect_level_touches(candles, lambda i: 100.0, "x", atr_series)
    assert touches == []


def test_detect_level_touches_increments_prior_touch_count():
    candles = [mk(i, 100, 101, 99, 100) for i in range(6)]  # touches every bar
    atr_series = [4.0] * 6
    touches = ls.detect_level_touches(candles, lambda i: 100.0, "x", atr_series, max_resolution_bars=1)
    assert [t.prior_touch_count for t in touches] == list(range(len(touches)))


# --- level_strength_score ---


def test_level_strength_score_rejects_empty_touches():
    with pytest.raises(ValueError, match="must not be empty"):
        ls.level_strength_score([], timeframe="1w")


def test_level_strength_score_golden_ratio_scores_higher():
    golden = ls.level_strength_score([touch(0)], timeframe="1w", level_ratio=0.618)
    plain = ls.level_strength_score([touch(0)], timeframe="1w", level_ratio=0.5)
    assert golden > plain
    assert golden == pytest.approx(plain * ls.GOLDEN_RATIO_BASE_WEIGHT / ls.DEFAULT_BASE_WEIGHT)


def test_level_strength_score_1618_also_counts_as_golden_ratio():
    a = ls.level_strength_score([touch(0)], timeframe="1w", level_ratio=0.618)
    b = ls.level_strength_score([touch(0)], timeframe="1w", level_ratio=1.618)
    assert a == pytest.approx(b)


def test_level_strength_score_higher_timeframe_scores_higher():
    weekly = ls.level_strength_score([touch(0)], timeframe="1w")
    hourly = ls.level_strength_score([touch(0)], timeframe="1h")
    assert weekly > hourly


def test_level_strength_score_unknown_timeframe_falls_back_to_weakest():
    unknown = ls.level_strength_score([touch(0)], timeframe="5m")
    hourly = ls.level_strength_score([touch(0)], timeframe="1h")
    assert unknown == pytest.approx(hourly)


def test_level_strength_score_decays_with_more_touches():
    fresh = ls.level_strength_score([touch(0, prior_touch_count=0)], timeframe="1w")
    tested = ls.level_strength_score([touch(0), touch(5, prior_touch_count=1)], timeframe="1w")
    assert fresh > tested


def test_level_strength_score_penalizes_prior_break():
    clean_history = [touch(0, ls.TouchOutcome.BOUNCE), touch(5, ls.TouchOutcome.BOUNCE, prior_touch_count=1)]
    broken_history = [touch(0, ls.TouchOutcome.BREAK), touch(5, ls.TouchOutcome.BOUNCE, prior_touch_count=1)]
    clean_score = ls.level_strength_score(clean_history, timeframe="1w")
    broken_score = ls.level_strength_score(broken_history, timeframe="1w")
    assert broken_score < clean_score
    assert broken_score == pytest.approx(clean_score * ls.ALREADY_BROKEN_PENALTY)


def test_level_strength_score_only_considers_earlier_touches_for_broken_penalty():
    # the LATEST touch itself breaking doesn't retroactively penalize
    # its own score -- only touches strictly before it do.
    only_touch_breaks = [touch(0, ls.TouchOutcome.BREAK)]
    score = ls.level_strength_score(only_touch_breaks, timeframe="1w")
    baseline = ls.level_strength_score([touch(0, ls.TouchOutcome.BOUNCE)], timeframe="1w")
    assert score == pytest.approx(baseline)
