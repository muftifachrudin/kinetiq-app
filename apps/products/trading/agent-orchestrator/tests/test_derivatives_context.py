import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import derivatives_context as dc  # noqa: E402
import fib_gann_timing as fgt  # noqa: E402

LONG = fgt.TradeDirection.LONG
SHORT = fgt.TradeDirection.SHORT


def day(n: int) -> datetime.date:
    return datetime.date(2026, 1, 1) + datetime.timedelta(days=n)


def mk_record(
    n: int,
    price_close: float,
    oi_close: float,
    funding_rate: float = 0.0001,
    global_ls_ratio: float = 1.0,
    top_ls_ratio: float = 1.0,
    long_liq_usd: float | None = None,
    short_liq_usd: float | None = None,
) -> dc.DailyDerivativesRecord:
    return dc.DailyDerivativesRecord(
        date=day(n),
        price_close=price_close,
        oi_close=oi_close,
        funding_rate=funding_rate,
        global_ls_ratio=global_ls_ratio,
        top_ls_ratio=top_ls_ratio,
        long_liq_usd=long_liq_usd,
        short_liq_usd=short_liq_usd,
    )


# --- _percentile_rank ---


def test_percentile_rank_midpoint_of_uniform_population():
    pop = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert dc._percentile_rank(3.0, pop) == pytest.approx(0.5)  # 2 below, 1 equal -> (2+0.5)/5


def test_percentile_rank_below_everything_is_zero():
    assert dc._percentile_rank(0.0, [1.0, 2.0, 3.0]) == pytest.approx(0.0)


def test_percentile_rank_above_everything_is_one():
    assert dc._percentile_rank(10.0, [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_percentile_rank_rejects_empty_population():
    with pytest.raises(ValueError, match="must not be empty"):
        dc._percentile_rank(1.0, [])


# --- compute_derivatives_context ---


def test_rejects_fewer_than_two_prior_records():
    records = [mk_record(0, 100.0, 1000.0)]
    with pytest.raises(ValueError, match="at least 2 records"):
        dc.compute_derivatives_context(records, day(1))


def test_never_reads_target_dates_own_record_even_if_present():
    # day(5)'s record has an absurd funding_rate that would dominate the
    # percentile if read -- but target_date=day(5) means only day 0-4 count.
    records = [mk_record(i, 100.0 + i, 1000.0 + i * 10, funding_rate=0.0001 * i) for i in range(5)]
    records.append(mk_record(5, 999.0, 999.0, funding_rate=99.0))
    ctx = dc.compute_derivatives_context(records, day(5))
    assert ctx.funding_percentile_365d < 1.0  # day 5's own 99.0 funding never entered the population
    assert ctx.window_size == 5


def test_window_size_caps_at_window_days():
    records = [mk_record(i, 100.0 + i, 1000.0) for i in range(50)]
    ctx = dc.compute_derivatives_context(records, day(50), window_days=10)
    assert ctx.window_size == 10


# --- fuel_quadrant ---


def test_fuel_quadrant_up_oi_up():
    records = [mk_record(0, 100.0, 1000.0), mk_record(1, 110.0, 1100.0)]
    ctx = dc.compute_derivatives_context(records, day(2))
    assert ctx.fuel_quadrant is dc.FuelQuadrant.UP_OI_UP


def test_fuel_quadrant_up_oi_down():
    records = [mk_record(0, 100.0, 1000.0), mk_record(1, 110.0, 900.0)]
    ctx = dc.compute_derivatives_context(records, day(2))
    assert ctx.fuel_quadrant is dc.FuelQuadrant.UP_OI_DOWN


def test_fuel_quadrant_down_oi_up():
    records = [mk_record(0, 100.0, 1000.0), mk_record(1, 90.0, 1100.0)]
    ctx = dc.compute_derivatives_context(records, day(2))
    assert ctx.fuel_quadrant is dc.FuelQuadrant.DOWN_OI_UP


def test_fuel_quadrant_down_oi_down():
    records = [mk_record(0, 100.0, 1000.0), mk_record(1, 90.0, 900.0)]
    ctx = dc.compute_derivatives_context(records, day(2))
    assert ctx.fuel_quadrant is dc.FuelQuadrant.DOWN_OI_DOWN


# --- funding_percentile_365d / global_ls_percentile_365d ---


def test_funding_percentile_reflects_position_in_trailing_window():
    records = [mk_record(i, 100.0, 1000.0, funding_rate=0.0001 * i) for i in range(10)]  # 0.0000..0.0009
    ctx = dc.compute_derivatives_context(records, day(10))
    # latest (day 9) funding_rate=0.0009 is the max of the 10-record window
    assert ctx.funding_percentile_365d == pytest.approx(0.95)  # 9 below, 1 equal -> (9+0.5)/10


def test_global_ls_percentile_reflects_position_in_trailing_window():
    records = [mk_record(i, 100.0, 1000.0, global_ls_ratio=1.0 + 0.1 * i) for i in range(10)]
    ctx = dc.compute_derivatives_context(records, day(10))
    assert ctx.global_ls_percentile_365d == pytest.approx(0.95)


# --- top_vs_global_divergence ---


def test_top_vs_global_divergence_is_signed_difference():
    records = [mk_record(0, 100.0, 1000.0), mk_record(1, 101.0, 1010.0, top_ls_ratio=2.0, global_ls_ratio=1.5)]
    ctx = dc.compute_derivatives_context(records, day(2))
    assert ctx.top_vs_global_divergence == pytest.approx(0.5)


# --- liq_cascade_flag ---


def test_liq_cascade_flag_true_when_above_p90_threshold():
    records = [mk_record(i, 100.0, 1000.0, long_liq_usd=10.0) for i in range(9)]
    records.append(mk_record(9, 100.0, 1000.0, long_liq_usd=1_000_000.0))  # extreme spike, latest day
    ctx = dc.compute_derivatives_context(records, day(10))
    assert ctx.liq_cascade_flag is True


def test_liq_cascade_flag_false_when_not_extreme():
    records = [mk_record(i, 100.0, 1000.0, long_liq_usd=10.0) for i in range(10)]
    ctx = dc.compute_derivatives_context(records, day(10))
    assert ctx.liq_cascade_flag is False


def test_liq_cascade_flag_false_when_liq_data_missing():
    records = [mk_record(i, 100.0, 1000.0, long_liq_usd=None) for i in range(10)]
    ctx = dc.compute_derivatives_context(records, day(10))
    assert ctx.liq_cascade_flag is False


# --- funding_contrarian_alignment / global_ls_contrarian_alignment ---


def test_funding_contrarian_alignment_high_percentile_favors_short():
    assert dc.funding_contrarian_alignment(SHORT, 0.95) == pytest.approx(0.95)
    assert dc.funding_contrarian_alignment(LONG, 0.95) == pytest.approx(0.05)


def test_funding_contrarian_alignment_low_percentile_favors_long():
    assert dc.funding_contrarian_alignment(LONG, 0.05) == pytest.approx(0.95)
    assert dc.funding_contrarian_alignment(SHORT, 0.05) == pytest.approx(0.05)


def test_funding_contrarian_alignment_midpoint_is_neutral():
    assert dc.funding_contrarian_alignment(LONG, 0.5) == pytest.approx(0.5)
    assert dc.funding_contrarian_alignment(SHORT, 0.5) == pytest.approx(0.5)


def test_global_ls_contrarian_alignment_matches_funding_convention():
    assert dc.global_ls_contrarian_alignment(SHORT, 0.9) == pytest.approx(0.9)
    assert dc.global_ls_contrarian_alignment(LONG, 0.9) == pytest.approx(0.1)


# --- top_vs_global_alignment ---


def test_top_vs_global_alignment_positive_divergence_favors_long():
    assert dc.top_vs_global_alignment(LONG, 0.5, scale=0.5) == pytest.approx(1.0)
    assert dc.top_vs_global_alignment(SHORT, 0.5, scale=0.5) == pytest.approx(0.0)


def test_top_vs_global_alignment_negative_divergence_favors_short():
    assert dc.top_vs_global_alignment(SHORT, -0.5, scale=0.5) == pytest.approx(1.0)
    assert dc.top_vs_global_alignment(LONG, -0.5, scale=0.5) == pytest.approx(0.0)


def test_top_vs_global_alignment_zero_divergence_is_neutral():
    assert dc.top_vs_global_alignment(LONG, 0.0) == pytest.approx(0.5)


def test_top_vs_global_alignment_clamps_beyond_scale():
    assert dc.top_vs_global_alignment(LONG, 5.0, scale=0.5) == pytest.approx(1.0)
    assert dc.top_vs_global_alignment(LONG, -5.0, scale=0.5) == pytest.approx(0.0)
