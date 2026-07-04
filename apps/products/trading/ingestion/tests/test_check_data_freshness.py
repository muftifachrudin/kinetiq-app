import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import check_data_freshness as cdf  # noqa: E402

UTC = datetime.timezone.utc
NOW = datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


def mk_response(ohlcv_max=None, funding_max=None, signal_heartbeat=None) -> str:
    return json.dumps({"rows": [{"ohlcv_max": ohlcv_max, "funding_max": funding_max, "signal_heartbeat": signal_heartbeat}]})


def iso(dt: datetime.datetime) -> str:
    return dt.isoformat()


def test_check_freshness_no_problems_when_all_fresh():
    response = mk_response(
        ohlcv_max=iso(NOW - datetime.timedelta(minutes=30)),
        funding_max=iso(NOW - datetime.timedelta(minutes=45)),
        signal_heartbeat=iso(NOW - datetime.timedelta(minutes=10)),
    )
    assert cdf.check_freshness(response, threshold_hours=3, now=NOW) == []


def test_check_freshness_flags_stale_ohlcv():
    response = mk_response(
        ohlcv_max=iso(NOW - datetime.timedelta(hours=4)),
        funding_max=iso(NOW - datetime.timedelta(minutes=10)),
        signal_heartbeat=iso(NOW - datetime.timedelta(minutes=10)),
    )
    problems = cdf.check_freshness(response, threshold_hours=3, now=NOW)
    assert len(problems) == 1
    assert "ohlcv" in problems[0]


def test_check_freshness_flags_missing_data_as_a_problem():
    response = mk_response(ohlcv_max=None, funding_max=iso(NOW), signal_heartbeat=iso(NOW))
    problems = cdf.check_freshness(response, threshold_hours=3, now=NOW)
    assert problems == ["ohlcv: NO DATA AT ALL"]


def test_check_freshness_flags_all_three_independently():
    response = mk_response(
        ohlcv_max=iso(NOW - datetime.timedelta(hours=10)),
        funding_max=iso(NOW - datetime.timedelta(hours=10)),
        signal_heartbeat=None,
    )
    problems = cdf.check_freshness(response, threshold_hours=3, now=NOW)
    assert len(problems) == 3


def test_check_freshness_boundary_exactly_at_threshold_is_not_stale():
    response = mk_response(
        ohlcv_max=iso(NOW - datetime.timedelta(hours=3)),
        funding_max=iso(NOW - datetime.timedelta(hours=3)),
        signal_heartbeat=iso(NOW - datetime.timedelta(hours=3)),
    )
    assert cdf.check_freshness(response, threshold_hours=3, now=NOW) == []


def test_check_freshness_uses_signal_heartbeat_not_max_signal_ts():
    # A quiet market with no new signal for hours is NORMAL (signal is a
    # sparse table by design) -- this function must never be handed
    # max(signal.ts) as evidence of staleness, only the data_source_health
    # heartbeat, which the workflow's own SQL query is responsible for
    # supplying under the "signal_heartbeat" key regardless of how sparse
    # the signal table itself is.
    response = mk_response(
        ohlcv_max=iso(NOW - datetime.timedelta(minutes=10)),
        funding_max=iso(NOW - datetime.timedelta(minutes=10)),
        signal_heartbeat=iso(NOW - datetime.timedelta(minutes=10)),
    )
    assert cdf.check_freshness(response, threshold_hours=3, now=NOW) == []


# --- main() (uses the REAL wall clock, unlike check_freshness() above --
# so these two use timestamps relative to actual now(), not the fixed NOW
# fixture) ---


def test_main_returns_zero_when_fresh():
    real_now = datetime.datetime.now(UTC)
    response = mk_response(
        ohlcv_max=iso(real_now - datetime.timedelta(minutes=10)),
        funding_max=iso(real_now - datetime.timedelta(minutes=10)),
        signal_heartbeat=iso(real_now - datetime.timedelta(minutes=10)),
    )
    assert cdf.main([response, "3"]) == 0


def test_main_returns_one_when_stale():
    response = mk_response(ohlcv_max=None, funding_max=None, signal_heartbeat=None)
    assert cdf.main([response, "3"]) == 1
