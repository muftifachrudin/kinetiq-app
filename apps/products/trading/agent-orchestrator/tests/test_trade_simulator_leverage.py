import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "validation" / "fib_gann_backtest"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402
import trade_simulator as ts  # noqa: E402

UTC = datetime.timezone.utc
LONG = fgt.TradeDirection.LONG
SHORT = fgt.TradeDirection.SHORT


def mk(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(
        ts=datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=i), open=o, high=h, low=l, close=c, volume=v
    )


def mk_exit_plan(direction, entry_price, stop_loss, take_profit) -> fgt.ExitPlan:
    return fgt.ExitPlan(
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profits=(take_profit,),
        risk_reward_ratio=abs(take_profit - entry_price) / abs(entry_price - stop_loss),
    )


# --- build_margin_context ---


def test_build_margin_context_rejects_non_positive_leverage():
    with pytest.raises(ValueError, match="leverage must be positive"):
        ts.build_margin_context(100.0, LONG, 0.0, ts.MarginMode.ISOLATED)


def test_build_margin_context_rejects_cross_buffer_on_isolated():
    with pytest.raises(ValueError, match="cross_buffer_pct only applies"):
        ts.build_margin_context(100.0, LONG, 10.0, ts.MarginMode.ISOLATED, cross_buffer_pct=0.01)


def test_build_margin_context_rejects_negative_cross_buffer():
    with pytest.raises(ValueError, match="must not be negative"):
        ts.build_margin_context(100.0, LONG, 10.0, ts.MarginMode.CROSS, cross_buffer_pct=-0.01)


def test_build_margin_context_rejects_leverage_with_no_cushion_left():
    # at maintenance_margin_rate=0.004, leverage=250 already consumes the
    # entire cushion (1/250 = 0.004 == mmr exactly -> cushion <= 0)
    with pytest.raises(ValueError, match="no cushion"):
        ts.build_margin_context(100.0, LONG, 250.0, ts.MarginMode.ISOLATED)


def test_build_margin_context_long_liquidation_below_entry():
    mc = ts.build_margin_context(100.0, LONG, 10.0, ts.MarginMode.ISOLATED, maintenance_margin_rate=0.004)
    # cushion = 0.1 - 0.004 = 0.096 -> liq = 100*(1-0.096) = 90.4
    assert mc.liquidation_price == pytest.approx(90.4)


def test_build_margin_context_short_liquidation_above_entry():
    mc = ts.build_margin_context(100.0, SHORT, 10.0, ts.MarginMode.ISOLATED, maintenance_margin_rate=0.004)
    assert mc.liquidation_price == pytest.approx(109.6)


def test_build_margin_context_cross_buffer_moves_liquidation_further_away():
    isolated = ts.build_margin_context(100.0, LONG, 10.0, ts.MarginMode.ISOLATED)
    cross = ts.build_margin_context(100.0, LONG, 10.0, ts.MarginMode.CROSS, cross_buffer_pct=0.05)
    assert cross.liquidation_price < isolated.liquidation_price  # more room before liquidating


def test_build_margin_context_higher_leverage_liquidates_closer_to_entry():
    low_lev = ts.build_margin_context(100.0, LONG, 5.0, ts.MarginMode.ISOLATED)
    high_lev = ts.build_margin_context(100.0, LONG, 20.0, ts.MarginMode.ISOLATED)
    assert high_lev.liquidation_price > low_lev.liquidation_price  # tighter cushion


# --- max_safe_leverage / assert_liquidation_safe ---


def test_max_safe_leverage_is_exactly_the_assert_boundary():
    entry, sl, atr = 100.0, 95.0, 2.0
    leverage = ts.max_safe_leverage(entry, sl, atr)
    mc = ts.build_margin_context(entry, LONG, leverage, ts.MarginMode.ISOLATED)
    ts.assert_liquidation_safe(entry, sl, atr, mc)  # must not raise -- exact boundary passes


def test_leverage_above_max_safe_raises_unsafe_leverage_error():
    entry, sl, atr = 100.0, 95.0, 2.0
    leverage = ts.max_safe_leverage(entry, sl, atr) * 1.01
    mc = ts.build_margin_context(entry, LONG, leverage, ts.MarginMode.ISOLATED)
    with pytest.raises(ts.UnsafeLeverageError):
        ts.assert_liquidation_safe(entry, sl, atr, mc)


def test_leverage_below_max_safe_does_not_raise():
    entry, sl, atr = 100.0, 95.0, 2.0
    leverage = ts.max_safe_leverage(entry, sl, atr) * 0.5
    mc = ts.build_margin_context(entry, LONG, leverage, ts.MarginMode.ISOLATED)
    ts.assert_liquidation_safe(entry, sl, atr, mc)


def test_max_safe_leverage_works_symmetrically_for_short():
    entry, sl, atr = 100.0, 105.0, 2.0
    leverage = ts.max_safe_leverage(entry, sl, atr)
    mc = ts.build_margin_context(entry, SHORT, leverage, ts.MarginMode.ISOLATED)
    ts.assert_liquidation_safe(entry, sl, atr, mc)


# --- simulate_leveraged_trade ---


def test_simulate_leveraged_trade_rejects_unsafe_leverage_before_walking():
    exit_plan = mk_exit_plan(LONG, 100.0, 95.0, 110.0)
    mc = ts.build_margin_context(100.0, LONG, 20.0, ts.MarginMode.ISOLATED)  # way above safe for a 5-pt SL, 2.0 ATR
    with pytest.raises(ts.UnsafeLeverageError):
        ts.simulate_leveraged_trade(exit_plan, [mk(1, 100, 101, 99, 100)], [], mk(0, 0, 0, 0, 0).ts, 5, mc, atr_value=2.0)


def test_simulate_leveraged_trade_liquidation_checked_before_sl_on_same_candle():
    # A safe-per-the-invariant setup (SL=92, liq=90.4, both within the
    # required buffer) still has liquidation SIT CLOSER to zero than SL
    # -- so a single violent wick that blows through both in one candle
    # must report LIQUIDATED, not STOP_LOSS, per the brief's explicit
    # "liquidation check SEBELUM SL check" priority rule.
    exit_plan = mk_exit_plan(LONG, 100.0, 92.0, 200.0)
    atr = 1.0
    mc = ts.build_margin_context(100.0, LONG, 10.0, ts.MarginMode.ISOLATED)  # liq at 90.4
    ts.assert_liquidation_safe(100.0, 92.0, atr, mc)  # sanity: this leverage IS safe re: the invariant
    granular = [mk(1, 100, 101, 88.0, 95)]  # wick to 88 -- below BOTH liq_price(90.4) and SL(92)
    result = ts.simulate_leveraged_trade(exit_plan, granular, [], mk(0, 0, 0, 0, 0).ts, 5, mc, atr_value=atr)
    assert result.exit_reason is ts.ExitReason.LIQUIDATED
    assert result.margin_return_pct == pytest.approx(-1.0)
    assert result.exit_price == pytest.approx(mc.liquidation_price)


def test_simulate_leveraged_trade_stop_loss_when_not_liquidated():
    exit_plan = mk_exit_plan(LONG, 100.0, 95.0, 110.0)
    atr = 2.0
    leverage = ts.max_safe_leverage(100.0, 95.0, atr) * 0.5  # comfortably safe leverage
    mc = ts.build_margin_context(100.0, LONG, leverage, ts.MarginMode.ISOLATED)
    granular = [mk(1, 100, 100.5, 94, 94.5)]  # touches SL, doesn't touch liquidation price
    result = ts.simulate_leveraged_trade(exit_plan, granular, [], mk(0, 0, 0, 0, 0).ts, 5, mc, atr_value=atr)
    assert result.exit_reason is ts.ExitReason.STOP_LOSS
    assert result.exit_price == pytest.approx(95.0)
    assert result.notional_return_pct == pytest.approx(-0.05)
    assert result.margin_return_pct == pytest.approx(-0.05 * leverage)


def test_simulate_leveraged_trade_take_profit_scales_by_leverage():
    exit_plan = mk_exit_plan(LONG, 100.0, 95.0, 110.0)
    atr = 2.0
    leverage = ts.max_safe_leverage(100.0, 95.0, atr) * 0.5
    mc = ts.build_margin_context(100.0, LONG, leverage, ts.MarginMode.ISOLATED)
    granular = [mk(1, 100, 111, 99, 110)]
    result = ts.simulate_leveraged_trade(exit_plan, granular, [], mk(0, 0, 0, 0, 0).ts, 5, mc, atr_value=atr)
    assert result.exit_reason is ts.ExitReason.TAKE_PROFIT
    assert result.notional_return_pct == pytest.approx(0.10)
    assert result.margin_return_pct == pytest.approx(0.10 * leverage)


def test_simulate_leveraged_trade_funding_erosion_triggers_liquidation_with_flat_price():
    # price sits flat the whole time (never approaches the static
    # liquidation price), but enough LONG-side funding cost accrues to
    # erode the entire cushion -- must still liquidate, on flat price
    # alone, exactly as the brief requires.
    exit_plan = mk_exit_plan(LONG, 100.0, 92.0, 200.0)  # 8pts away, safe for leverage 10 at ATR=1
    atr = 1.0
    mc = ts.build_margin_context(100.0, LONG, 10.0, ts.MarginMode.ISOLATED)  # cushion = 0.096
    entry_ts = mk(0, 0, 0, 0, 0).ts
    granular = [mk(i, 100, 100.2, 99.8, 100) for i in range(1, 6)]  # flat candles, never near liq_price=90.4
    # 5 funding events of 0.02 each = 0.10 cumulative cost, exceeds the 0.096 cushion
    funding_events = [ts.FundingEvent(ts=mk(i, 0, 0, 0, 0).ts, rate=0.02) for i in range(1, 6)]
    result = ts.simulate_leveraged_trade(exit_plan, granular, funding_events, entry_ts, 10, mc, atr_value=atr)
    assert result.exit_reason is ts.ExitReason.LIQUIDATED
    assert result.margin_return_pct == pytest.approx(-1.0)


def test_simulate_leveraged_trade_short_funding_erosion_also_liquidates():
    exit_plan = mk_exit_plan(SHORT, 100.0, 108.0, 50.0)  # 8pts away, safe for leverage 10 at ATR=1
    atr = 1.0
    mc = ts.build_margin_context(100.0, SHORT, 10.0, ts.MarginMode.ISOLATED)
    entry_ts = mk(0, 0, 0, 0, 0).ts
    granular = [mk(i, 100, 100.2, 99.8, 100) for i in range(1, 6)]
    # SHORT accrues -rate as cost, so a NEGATIVE funding rate is what
    # costs a short (rate<0 means shorts pay longs)
    funding_events = [ts.FundingEvent(ts=mk(i, 0, 0, 0, 0).ts, rate=-0.02) for i in range(1, 6)]
    result = ts.simulate_leveraged_trade(exit_plan, granular, funding_events, entry_ts, 10, mc, atr_value=atr)
    assert result.exit_reason is ts.ExitReason.LIQUIDATED


def test_simulate_leveraged_trade_funding_events_before_entry_are_ignored():
    exit_plan = mk_exit_plan(LONG, 100.0, 92.0, 200.0)
    atr = 1.0
    mc = ts.build_margin_context(100.0, LONG, 10.0, ts.MarginMode.ISOLATED)
    entry_ts = mk(5, 0, 0, 0, 0).ts
    granular = [mk(6, 100, 100.2, 99.8, 100)]
    stale_event = ts.FundingEvent(ts=mk(1, 0, 0, 0, 0).ts, rate=0.5)  # long before entry -- must not count
    result = ts.simulate_leveraged_trade(exit_plan, granular, [stale_event], entry_ts, 5, mc, atr_value=atr)
    assert result.exit_reason is ts.ExitReason.TIMEOUT  # would be LIQUIDATED if the stale event were wrongly counted


def test_simulate_leveraged_trade_cross_mode_survives_where_isolated_would_liquidate():
    exit_plan = mk_exit_plan(LONG, 100.0, 92.0, 200.0)
    atr = 1.0
    entry_ts = mk(0, 0, 0, 0, 0).ts
    granular = [mk(1, 100, 101, 88.0, 95)]  # wick to 88
    isolated = ts.build_margin_context(100.0, LONG, 10.0, ts.MarginMode.ISOLATED)  # liq at 90.4 -- touched by 88
    cross = ts.build_margin_context(100.0, LONG, 10.0, ts.MarginMode.CROSS, cross_buffer_pct=0.05)  # liq at 85.4 -- NOT touched by 88
    result_isolated = ts.simulate_leveraged_trade(exit_plan, granular, [], entry_ts, 5, isolated, atr_value=atr)
    result_cross = ts.simulate_leveraged_trade(exit_plan, granular, [], entry_ts, 5, cross, atr_value=atr)
    assert result_isolated.exit_reason is ts.ExitReason.LIQUIDATED
    assert result_cross.exit_reason is not ts.ExitReason.LIQUIDATED
    assert cross.liquidation_price < isolated.liquidation_price


def test_simulate_leveraged_trade_censored_on_timeout_when_data_runs_out():
    exit_plan = mk_exit_plan(LONG, 100.0, 95.0, 110.0)
    atr = 2.0
    leverage = ts.max_safe_leverage(100.0, 95.0, atr) * 0.5
    mc = ts.build_margin_context(100.0, LONG, leverage, ts.MarginMode.ISOLATED)
    granular = [mk(1, 100, 100.2, 99.8, 100)]  # never resolves, only 1 candle available
    result = ts.simulate_leveraged_trade(exit_plan, granular, [], mk(0, 0, 0, 0, 0).ts, 5, mc, atr_value=atr)
    assert result.exit_reason is ts.ExitReason.TIMEOUT
    assert result.censored is True


def test_simulate_leveraged_trade_rejects_empty_candles():
    exit_plan = mk_exit_plan(LONG, 100.0, 95.0, 110.0)
    mc = ts.build_margin_context(100.0, LONG, 2.0, ts.MarginMode.ISOLATED)
    with pytest.raises(ValueError, match="must not be empty"):
        ts.simulate_leveraged_trade(exit_plan, [], [], mk(0, 0, 0, 0, 0).ts, 5, mc, atr_value=2.0)
