import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "connectors", "cex"))
import worker  # noqa: E402

UTC = datetime.timezone.utc


class FakeDb:
    def close(self):
        pass


# --- seconds_until_next_close ---


def test_seconds_until_next_close_1h_mid_hour():
    now = datetime.datetime(2024, 1, 1, 14, 23, 0, tzinfo=UTC)
    assert worker.seconds_until_next_close("1h", now, buffer_seconds=10) == pytest.approx(37 * 60 + 10)


def test_seconds_until_next_close_1h_right_at_boundary():
    now = datetime.datetime(2024, 1, 1, 14, 0, 0, tzinfo=UTC)
    # at exactly the boundary, the NEXT close is a full hour away, not 0
    assert worker.seconds_until_next_close("1h", now, buffer_seconds=10) == pytest.approx(3600 + 10)


def test_seconds_until_next_close_4h():
    now = datetime.datetime(2024, 1, 1, 5, 0, 0, tzinfo=UTC)
    assert worker.seconds_until_next_close("4h", now, buffer_seconds=0) == pytest.approx(3 * 3600)


def test_seconds_until_next_close_default_buffer_is_positive():
    now = datetime.datetime(2024, 1, 1, 14, 59, 59, tzinfo=UTC)
    assert worker.seconds_until_next_close("1h", now) > 0


# --- run_forever (pure sequencing, all deps injected) ---


def test_run_forever_runs_backfill_before_first_poll():
    calls = []

    def fake_setup(db, venues, symbols):
        return "contexts"

    def fake_backfill(db, contexts, timeframe, since):
        calls.append(("backfill", since))

    def fake_poll(db, contexts, timeframe, limit):
        calls.append(("poll",))

    stop_after = {"n": 1}

    def should_stop():
        stop_after["n"] -= 1
        return stop_after["n"] < 0

    worker.run_forever(
        ["binance"], ["BTC/USDT:USDT"], "1h", poll_limit=5, backfill_since_days=30,
        should_stop=should_stop, sleep_fn=lambda s: None, now_fn=lambda: datetime.datetime(2024, 1, 1, tzinfo=UTC),
        get_session_fn=lambda: FakeDb(), setup_venues_fn=fake_setup, backfill_run_fn=fake_backfill, poll_once_fn=fake_poll,
        generate_signals_fn=lambda *a: None,
    )
    assert calls[0][0] == "backfill"
    assert calls[1] == ("poll",)


def test_run_forever_skips_backfill_when_none():
    calls = []
    seen = {"n": 0}

    def should_stop():
        seen["n"] += 1
        return seen["n"] > 1  # False on the 1st check (one loop iteration runs), True on the 2nd

    worker.run_forever(
        ["binance"], ["BTC/USDT:USDT"], "1h", poll_limit=5, backfill_since_days=None,
        should_stop=should_stop, sleep_fn=lambda s: None, now_fn=lambda: datetime.datetime(2024, 1, 1, tzinfo=UTC),
        get_session_fn=lambda: FakeDb(), setup_venues_fn=lambda db, v, s: "ctx",
        backfill_run_fn=lambda *a: calls.append("backfill"), poll_once_fn=lambda *a: calls.append("poll"),
        generate_signals_fn=lambda *a: None,
    )
    assert calls == ["poll"]


def test_run_forever_polls_once_per_loop_iteration_until_should_stop():
    poll_count = {"n": 0}
    iterations = {"n": 0}

    def fake_poll(db, contexts, timeframe, limit):
        poll_count["n"] += 1

    def should_stop():
        iterations["n"] += 1
        return iterations["n"] > 3

    worker.run_forever(
        ["binance"], ["BTC/USDT:USDT"], "1h", poll_limit=5, backfill_since_days=None,
        should_stop=should_stop, sleep_fn=lambda s: None, now_fn=lambda: datetime.datetime(2024, 1, 1, tzinfo=UTC),
        get_session_fn=lambda: FakeDb(), setup_venues_fn=lambda db, v, s: "ctx",
        backfill_run_fn=lambda *a: None, poll_once_fn=fake_poll,
        generate_signals_fn=lambda *a: None,
    )
    assert poll_count["n"] == 3


def test_run_forever_computes_backfill_since_from_now_fn_and_days():
    captured = {}

    def fake_backfill(db, contexts, timeframe, since):
        captured["since"] = since

    worker.run_forever(
        ["binance"], ["BTC/USDT:USDT"], "1h", poll_limit=5, backfill_since_days=10,
        should_stop=lambda: True, sleep_fn=lambda s: None, now_fn=lambda: datetime.datetime(2024, 1, 11, tzinfo=UTC),
        get_session_fn=lambda: FakeDb(), setup_venues_fn=lambda db, v, s: "ctx",
        backfill_run_fn=fake_backfill, poll_once_fn=lambda *a: None,
        generate_signals_fn=lambda *a: None,
    )
    assert captured["since"] == datetime.datetime(2024, 1, 1, tzinfo=UTC)


# --- generate_signals_fn wiring (F0e P3) ---


def _one_shot_should_stop():
    stop_after = {"n": 1}

    def should_stop():
        stop_after["n"] -= 1
        return stop_after["n"] < 0

    return should_stop


def test_run_forever_runs_signal_generation_after_poll_by_default():
    calls = []
    worker.run_forever(
        ["binance"], ["BTC/USDT:USDT"], "1h", poll_limit=5, backfill_since_days=None,
        should_stop=_one_shot_should_stop(), sleep_fn=lambda s: None, now_fn=lambda: datetime.datetime(2024, 1, 1, tzinfo=UTC),
        get_session_fn=lambda: FakeDb(), setup_venues_fn=lambda db, v, s: "ctx",
        backfill_run_fn=lambda *a: None, poll_once_fn=lambda *a: calls.append("poll"),
        generate_signals_fn=lambda *a: calls.append("signals"),
    )
    assert calls == ["poll", "signals"]  # signals AFTER poll, same freshly-polled candles


def test_run_forever_skips_signal_generation_when_disabled():
    calls = []
    worker.run_forever(
        ["binance"], ["BTC/USDT:USDT"], "1h", poll_limit=5, backfill_since_days=None,
        should_stop=_one_shot_should_stop(), sleep_fn=lambda s: None, now_fn=lambda: datetime.datetime(2024, 1, 1, tzinfo=UTC),
        get_session_fn=lambda: FakeDb(), setup_venues_fn=lambda db, v, s: "ctx",
        backfill_run_fn=lambda *a: None, poll_once_fn=lambda *a: calls.append("poll"),
        generate_signals=False, generate_signals_fn=lambda *a: calls.append("signals"),
    )
    assert calls == ["poll"]


def test_run_forever_skips_signal_generation_for_non_1h_timeframe():
    # signal_runner.py/fib_gann_timing.py's HTF resampling and ATR period
    # assume a 1h entry timeframe -- running this for any other --timeframe
    # would be silently meaningless, not genuinely supported.
    calls = []
    worker.run_forever(
        ["binance"], ["BTC/USDT:USDT"], "4h", poll_limit=5, backfill_since_days=None,
        should_stop=_one_shot_should_stop(), sleep_fn=lambda s: None, now_fn=lambda: datetime.datetime(2024, 1, 1, tzinfo=UTC),
        get_session_fn=lambda: FakeDb(), setup_venues_fn=lambda db, v, s: "ctx",
        backfill_run_fn=lambda *a: None, poll_once_fn=lambda *a: calls.append("poll"),
        generate_signals_fn=lambda *a: calls.append("signals"),
    )
    assert calls == ["poll"]


def test_run_forever_calls_generate_signals_fn_with_db_contexts_timeframe():
    captured = {}

    def fake_setup(db, venues, symbols):
        return "the-contexts"

    worker.run_forever(
        ["binance"], ["BTC/USDT:USDT"], "1h", poll_limit=5, backfill_since_days=None,
        should_stop=_one_shot_should_stop(), sleep_fn=lambda s: None, now_fn=lambda: datetime.datetime(2024, 1, 1, tzinfo=UTC),
        get_session_fn=lambda: FakeDb(), setup_venues_fn=fake_setup,
        backfill_run_fn=lambda *a: None, poll_once_fn=lambda *a: None,
        generate_signals_fn=lambda db, contexts, timeframe: captured.update(contexts=contexts, timeframe=timeframe),
    )
    assert captured["contexts"] == "the-contexts"
    assert captured["timeframe"] == "1h"
