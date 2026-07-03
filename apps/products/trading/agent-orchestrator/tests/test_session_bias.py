import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402
import session_bias as sb  # noqa: E402

UTC = datetime.timezone.utc


def ts_at(year, month, day, hour) -> datetime.datetime:
    return datetime.datetime(year, month, day, hour, tzinfo=UTC)


def mk(ts: datetime.datetime, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(ts=ts, open=o, high=h, low=l, close=c, volume=v)


# --- session_of ---


def test_session_of_rejects_naive_datetime():
    with pytest.raises(ValueError, match="timezone-aware"):
        sb.session_of(datetime.datetime(2026, 1, 1, 3))


def test_session_of_asia_hours():
    assert sb.session_of(ts_at(2026, 1, 1, 0)) is sb.TradingSession.ASIA
    assert sb.session_of(ts_at(2026, 1, 1, 7)) is sb.TradingSession.ASIA


def test_session_of_london_only_hours():
    assert sb.session_of(ts_at(2026, 1, 1, 8)) is sb.TradingSession.LONDON
    assert sb.session_of(ts_at(2026, 1, 1, 12)) is sb.TradingSession.LONDON


def test_session_of_london_ny_overlap_hours():
    assert sb.session_of(ts_at(2026, 1, 1, 13)) is sb.TradingSession.LONDON_NY_OVERLAP
    assert sb.session_of(ts_at(2026, 1, 1, 15)) is sb.TradingSession.LONDON_NY_OVERLAP


def test_session_of_new_york_only_hours():
    assert sb.session_of(ts_at(2026, 1, 1, 16)) is sb.TradingSession.NEW_YORK
    assert sb.session_of(ts_at(2026, 1, 1, 20)) is sb.TradingSession.NEW_YORK


def test_session_of_off_hours():
    assert sb.session_of(ts_at(2026, 1, 1, 21)) is sb.TradingSession.OFF_HOURS
    assert sb.session_of(ts_at(2026, 1, 1, 23)) is sb.TradingSession.OFF_HOURS


def test_session_of_boundary_is_half_open():
    # end hour is exclusive -- hour 8 belongs to LONDON, not ASIA
    assert sb.session_of(ts_at(2026, 1, 1, 8)) is sb.TradingSession.LONDON
    assert sb.session_of(ts_at(2026, 1, 1, 7)) is sb.TradingSession.ASIA


def test_session_of_converts_non_utc_timezone():
    # 20:00 in UTC-5 is 01:00 UTC the next day -- ASIA, not NEW_YORK
    tz = datetime.timezone(datetime.timedelta(hours=-5))
    ts = datetime.datetime(2026, 1, 1, 20, tzinfo=tz)
    assert sb.session_of(ts) is sb.TradingSession.ASIA


def test_session_of_custom_boundaries():
    custom = {"asia": (0, 6), "london": (6, 12), "new_york": (12, 18)}
    assert sb.session_of(ts_at(2026, 1, 1, 7), boundaries=custom) is sb.TradingSession.LONDON


# --- group_into_session_blocks ---


def test_group_into_session_blocks_rejects_empty():
    with pytest.raises(ValueError, match="must not be empty"):
        sb.group_into_session_blocks([])


def test_group_into_session_blocks_merges_consecutive_same_session():
    candles = [
        mk(ts_at(2026, 1, 1, 0), 100, 101, 99, 100.5),
        mk(ts_at(2026, 1, 1, 1), 100.5, 102, 100, 101),
        mk(ts_at(2026, 1, 1, 2), 101, 103, 100.5, 102),
    ]
    blocks = sb.group_into_session_blocks(candles)
    assert len(blocks) == 1
    assert blocks[0].session is sb.TradingSession.ASIA
    assert blocks[0].candle_count == 3
    assert blocks[0].open_price == pytest.approx(100.0)
    assert blocks[0].close_price == pytest.approx(102.0)
    assert blocks[0].return_pct == pytest.approx(0.02)


def test_group_into_session_blocks_splits_on_session_change():
    candles = [
        mk(ts_at(2026, 1, 1, 7), 100, 101, 99, 100.5),  # ASIA
        mk(ts_at(2026, 1, 1, 8), 100.5, 102, 100, 101),  # LONDON -- new block
    ]
    blocks = sb.group_into_session_blocks(candles)
    assert len(blocks) == 2
    assert blocks[0].session is sb.TradingSession.ASIA
    assert blocks[1].session is sb.TradingSession.LONDON


def test_group_into_session_blocks_splits_on_date_change_even_if_same_session():
    # both hour 3, but different calendar days -- must be 2 separate blocks,
    # not merged into one giant "all Asia sessions ever" block.
    candles = [
        mk(ts_at(2026, 1, 1, 3), 100, 101, 99, 100.5),
        mk(ts_at(2026, 1, 2, 3), 105, 106, 104, 105.5),
    ]
    blocks = sb.group_into_session_blocks(candles)
    assert len(blocks) == 2
    assert blocks[0].date == datetime.date(2026, 1, 1)
    assert blocks[1].date == datetime.date(2026, 1, 2)


# --- compute_session_bias ---


def test_compute_session_bias_rejects_empty():
    with pytest.raises(ValueError, match="must not be empty"):
        sb.compute_session_bias([])


def test_compute_session_bias_positive_fraction_and_mean():
    blocks = [
        sb.SessionBlock(sb.TradingSession.ASIA, datetime.date(2026, 1, 1), 100.0, 102.0, 3, 0.02),
        sb.SessionBlock(sb.TradingSession.ASIA, datetime.date(2026, 1, 2), 100.0, 99.0, 3, -0.01),
        sb.SessionBlock(sb.TradingSession.ASIA, datetime.date(2026, 1, 3), 100.0, 101.0, 3, 0.01),
    ]
    stats = sb.compute_session_bias(blocks)
    asia = stats[sb.TradingSession.ASIA]
    assert asia.block_count == 3
    assert asia.positive_block_fraction == pytest.approx(2 / 3)
    assert asia.mean_return_pct == pytest.approx((0.02 - 0.01 + 0.01) / 3)
    assert asia.median_return_pct == pytest.approx(0.01)


def test_compute_session_bias_groups_sessions_independently():
    blocks = [
        sb.SessionBlock(sb.TradingSession.ASIA, datetime.date(2026, 1, 1), 100.0, 105.0, 3, 0.05),
        sb.SessionBlock(sb.TradingSession.LONDON, datetime.date(2026, 1, 1), 105.0, 100.0, 3, -0.0476),
    ]
    stats = sb.compute_session_bias(blocks)
    assert set(stats.keys()) == {sb.TradingSession.ASIA, sb.TradingSession.LONDON}
    assert stats[sb.TradingSession.ASIA].positive_block_fraction == pytest.approx(1.0)
    assert stats[sb.TradingSession.LONDON].positive_block_fraction == pytest.approx(0.0)
