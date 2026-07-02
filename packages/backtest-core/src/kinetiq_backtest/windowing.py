"""Walk-forward window generators. See types.py for why there are two
distinct schemes rather than one, and why WalkForwardWindow itself doesn't
care which one produced it.
"""

import datetime

from dateutil.relativedelta import relativedelta

from kinetiq_backtest.types import WalkForwardWindow, WindowMode, require_utc


def generate_windows_by_calendar(
    start: datetime.datetime,
    end: datetime.datetime,
    train_months: int,
    test_months: int,
    embargo_days: int = 0,
    step_months: int | None = None,
    mode: WindowMode = WindowMode.ANCHORED,
) -> list[WalkForwardWindow]:
    """Calendar-duration windows (what fib_gann_backtest uses). Month
    arithmetic goes through dateutil.relativedelta specifically because
    plain timedelta(days=30*n) silently drifts across months of different
    length (28/29/30/31 days) and across leap years -- relativedelta walks
    real calendar months instead.

    step_months defaults to test_months (non-overlapping, back-to-back test
    windows). Pass a smaller step_months for overlapping test windows --
    validate_window_set() requires allow_test_overlap=True to accept those.

    Returns [] if [start, end) isn't long enough to fit even one window,
    rather than raising or looping forever.
    """
    require_utc(start, "start")
    require_utc(end, "end")
    if train_months <= 0 or test_months <= 0:
        raise ValueError("train_months and test_months must be positive")
    if step_months is None:
        step_months = test_months
    if step_months <= 0:
        raise ValueError("step_months must be positive")

    embargo = datetime.timedelta(days=embargo_days)
    windows: list[WalkForwardWindow] = []
    window_id = 0

    while True:
        if mode == WindowMode.ANCHORED:
            train_start = start
            train_end = start + relativedelta(months=train_months + window_id * step_months)
        else:
            train_start = start + relativedelta(months=window_id * step_months)
            train_end = train_start + relativedelta(months=train_months)

        test_start = train_end + embargo
        test_end = test_start + relativedelta(months=test_months)

        if test_end > end:
            break

        windows.append(
            WalkForwardWindow(
                window_id=window_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        window_id += 1

    return windows


def generate_windows_by_candles(
    candle_timestamps: list[datetime.datetime],
    in_sample_len: int,
    out_sample_len: int,
    warmup_len: int = 0,
    step: int | None = None,
    mode: WindowMode = WindowMode.ROLLING,
) -> list[WalkForwardWindow]:
    """Candle-count-driven windows, matching the scheme ai-perp-bot-core's
    MARKOVIZ V5 already uses (src/walkforward.ts: isLen=2000, oosLen=700,
    warmup=200, rolling mode -- confirmed by reading that file directly,
    not assumed). Ported as index-driven logic rather than a hardcoded
    15-minute-bar duration, so it works at any candle interval. Returns the
    real timestamp at each computed candle index, not a synthetic offset.

    Note this generates ROLLING by default (MARKOVIZ V5's actual mode) --
    calendar windows default to ANCHORED instead (see
    generate_windows_by_calendar); the two schemes were tuned independently
    and there's no evidence either config should be forced onto the other.
    """
    if in_sample_len <= 0 or out_sample_len <= 0:
        raise ValueError("in_sample_len and out_sample_len must be positive")
    if warmup_len < 0:
        raise ValueError("warmup_len must be non-negative")
    if step is None:
        step = out_sample_len
    if step <= 0:
        raise ValueError("step must be positive")
    for i, ts in enumerate(candle_timestamps):
        require_utc(ts, f"candle_timestamps[{i}]")
    if candle_timestamps != sorted(candle_timestamps):
        raise ValueError("candle_timestamps must be sorted ascending")

    n = len(candle_timestamps)
    train_len = warmup_len + in_sample_len
    windows: list[WalkForwardWindow] = []
    window_id = 0

    while True:
        if mode == WindowMode.ANCHORED:
            train_start_idx = 0
            train_end_idx = train_len + window_id * step
        else:
            train_start_idx = window_id * step
            train_end_idx = train_start_idx + train_len

        test_start_idx = train_end_idx
        test_end_idx = test_start_idx + out_sample_len

        if test_end_idx > n:
            break

        windows.append(
            WalkForwardWindow(
                window_id=window_id,
                train_start=candle_timestamps[train_start_idx],
                train_end=candle_timestamps[train_end_idx - 1],
                test_start=candle_timestamps[test_start_idx],
                test_end=candle_timestamps[test_end_idx - 1],
            )
        )
        window_id += 1

    return windows
