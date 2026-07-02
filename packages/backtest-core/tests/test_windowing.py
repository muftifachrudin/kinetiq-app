import datetime

import pytest
from kinetiq_backtest import (
    WalkForwardWindow,
    WindowMode,
    generate_windows_by_calendar,
    generate_windows_by_candles,
    validate_window_set,
)

UTC = datetime.timezone.utc


def utc(*args) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=UTC)


# --- naive datetime rejection (docs/prd.md validation harness brief, Section 7) ---


def test_calendar_rejects_naive_start():
    with pytest.raises(ValueError, match="timezone-aware"):
        generate_windows_by_calendar(datetime.datetime(2024, 1, 1), utc(2025, 1, 1), 3, 1)


def test_calendar_rejects_naive_end():
    with pytest.raises(ValueError, match="timezone-aware"):
        generate_windows_by_calendar(utc(2024, 1, 1), datetime.datetime(2025, 1, 1), 3, 1)


def test_candles_rejects_naive_timestamp():
    candles = [utc(2024, 1, 1), datetime.datetime(2024, 1, 1, 1), utc(2024, 1, 1, 2)]
    with pytest.raises(ValueError, match="timezone-aware"):
        generate_windows_by_candles(candles, in_sample_len=1, out_sample_len=1)


def test_window_construction_rejects_naive_datetime():
    with pytest.raises(ValueError, match="timezone-aware"):
        WalkForwardWindow(0, datetime.datetime(2024, 1, 1), utc(2024, 2, 1), utc(2024, 2, 1), utc(2024, 3, 1))


# --- month-length variance + leap year (Section 7) ---


def test_calendar_handles_month_length_variance_from_day_31():
    # Jan 31 + 1 month must land on Feb 29 (2024 is a leap year), not error
    # or silently skip to March -- relativedelta's job, verify it actually happens.
    ws = generate_windows_by_calendar(utc(2024, 1, 31), utc(2024, 4, 1), train_months=1, test_months=1)
    assert ws[0].train_end == utc(2024, 2, 29)


def test_calendar_leap_year_test_window_crosses_feb_29():
    ws = generate_windows_by_calendar(utc(2023, 12, 1), utc(2024, 3, 2), train_months=2, test_months=1)
    assert len(ws) == 1
    assert ws[0].test_start == utc(2024, 2, 1)
    assert ws[0].test_end == utc(2024, 3, 1)


def test_calendar_non_leap_year_feb_has_28_days():
    ws = generate_windows_by_calendar(utc(2023, 1, 31), utc(2023, 4, 1), train_months=1, test_months=1)
    assert ws[0].train_end == utc(2023, 2, 28)


# --- range too short returns [] instead of hanging (Section 7) ---


def test_calendar_too_short_range_returns_empty_list():
    ws = generate_windows_by_calendar(utc(2024, 1, 1), utc(2024, 2, 1), train_months=3, test_months=1)
    assert ws == []


def test_candles_too_short_range_returns_empty_list():
    candles = [utc(2024, 1, 1) + datetime.timedelta(hours=i) for i in range(500)]
    ws = generate_windows_by_candles(candles, in_sample_len=2000, out_sample_len=700, warmup_len=200)
    assert ws == []


# --- mode behavior ---


def test_calendar_anchored_train_expands_test_window_fixed_size():
    ws = generate_windows_by_calendar(
        utc(2024, 1, 1), utc(2024, 12, 1), train_months=3, test_months=1, mode=WindowMode.ANCHORED
    )
    assert all(w.train_start == utc(2024, 1, 1) for w in ws)
    assert [w.train_end for w in ws] == [utc(2024, m, 1) for m in range(4, 4 + len(ws))]


def test_calendar_rolling_train_slides_fixed_size():
    ws = generate_windows_by_calendar(
        utc(2024, 1, 1), utc(2024, 12, 1), train_months=3, test_months=1, mode=WindowMode.ROLLING
    )
    for w in ws:
        # dateutil relativedelta guarantees exactly 3 calendar months, so this
        # is safe even though month lengths vary (28-31 days).
        assert w.train_start + _months(3) == w.train_end


def _months(n):
    from dateutil.relativedelta import relativedelta

    return relativedelta(months=n)


def test_candles_rolling_matches_ai_perp_bot_core_markoviz_v5_params():
    # in_sample=2000, out_sample=700, warmup=200, rolling -- confirmed by
    # reading ai-perp-bot-core/src/walkforward.ts directly, not assumed.
    candles = [utc(2024, 1, 1) + datetime.timedelta(hours=i) for i in range(6000)]
    ws = generate_windows_by_candles(candles, in_sample_len=2000, out_sample_len=700, warmup_len=200)
    assert len(ws) == 5
    # each window's train span covers exactly warmup+in_sample candles
    assert ws[0].train_start == candles[0]
    assert ws[0].train_end == candles[2199]
    assert ws[0].test_start == candles[2200]
    assert ws[0].test_end == candles[2899]
    # step defaults to out_sample_len (700) -- window 1 starts 700 candles later
    assert ws[1].train_start == candles[700]


def test_candles_anchored_train_expands():
    candles = [utc(2024, 1, 1) + datetime.timedelta(hours=i) for i in range(5000)]
    ws = generate_windows_by_candles(
        candles, in_sample_len=1000, out_sample_len=500, warmup_len=0, mode=WindowMode.ANCHORED
    )
    assert all(w.train_start == candles[0] for w in ws)
    assert ws[1].train_end == candles[1499]  # train_len(1000) + 1*step(500) - 1


# --- validate_window_set ---


def test_validate_rejects_duplicate_window_id():
    w1 = WalkForwardWindow(0, utc(2024, 1, 1), utc(2024, 2, 1), utc(2024, 2, 1), utc(2024, 3, 1))
    w2 = WalkForwardWindow(0, utc(2024, 3, 1), utc(2024, 4, 1), utc(2024, 4, 1), utc(2024, 5, 1))
    with pytest.raises(ValueError, match="duplicate window_id"):
        validate_window_set([w1, w2])


def test_validate_rejects_embargo_gap_too_short():
    w = WalkForwardWindow(0, utc(2024, 1, 1), utc(2024, 2, 1), utc(2024, 2, 1), utc(2024, 3, 1))
    with pytest.raises(ValueError, match="embargo gap"):
        validate_window_set([w], embargo=datetime.timedelta(days=1))


def test_validate_accepts_sufficient_embargo_gap():
    w = WalkForwardWindow(0, utc(2024, 1, 1), utc(2024, 2, 1), utc(2024, 2, 2), utc(2024, 3, 1))
    validate_window_set([w], embargo=datetime.timedelta(days=1))  # must not raise


def test_walkforward_window_rejects_leak_at_construction():
    with pytest.raises(ValueError, match="data leak"):
        WalkForwardWindow(0, utc(2024, 1, 1), utc(2024, 3, 1), utc(2024, 2, 1), utc(2024, 4, 1))


def test_validate_rejects_overlapping_test_windows_by_default():
    a = WalkForwardWindow(0, utc(2024, 1, 1), utc(2024, 2, 1), utc(2024, 2, 1), utc(2024, 3, 15))
    b = WalkForwardWindow(1, utc(2024, 1, 1), utc(2024, 3, 1), utc(2024, 3, 1), utc(2024, 4, 1))
    with pytest.raises(ValueError, match="overlapping test ranges"):
        validate_window_set([a, b])


def test_validate_allows_overlapping_test_windows_when_flagged():
    a = WalkForwardWindow(0, utc(2024, 1, 1), utc(2024, 2, 1), utc(2024, 2, 1), utc(2024, 3, 15))
    b = WalkForwardWindow(1, utc(2024, 1, 1), utc(2024, 3, 1), utc(2024, 3, 1), utc(2024, 4, 1))
    validate_window_set([a, b], allow_test_overlap=True)  # must not raise


def test_calendar_step_months_smaller_than_test_months_produces_overlap():
    # step_months < test_months -- explicitly requested overlapping windows,
    # must be accepted by validate_window_set only with allow_test_overlap=True.
    ws = generate_windows_by_calendar(
        utc(2024, 1, 1), utc(2024, 6, 1), train_months=2, test_months=2, step_months=1
    )
    with pytest.raises(ValueError, match="overlapping test ranges"):
        validate_window_set(ws)
    validate_window_set(ws, allow_test_overlap=True)


# --- regression / golden-output guard ---
# Self-regression only: protects against unintended future changes to this
# generator's own output for a fixed config. NOT a byte-exact replay of
# ai-perp-bot-core's live TypeScript runtime output -- that code isn't
# executable from here, so there is no ground truth to diff against beyond
# the confirmed parameter values themselves (isLen/oosLen/warmup/mode).


def test_candles_golden_output_for_markoviz_v5_default_params():
    candles = [utc(2024, 1, 1) + datetime.timedelta(hours=i) for i in range(3500)]
    ws = generate_windows_by_candles(candles, in_sample_len=2000, out_sample_len=700, warmup_len=200)
    assert [(w.window_id, w.train_start, w.test_end) for w in ws] == [
        (0, utc(2024, 1, 1), candles[2899]),
    ]
