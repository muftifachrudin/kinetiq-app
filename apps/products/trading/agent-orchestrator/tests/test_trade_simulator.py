import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "validation" / "fib_gann_backtest"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402

UTC = datetime.timezone.utc


def mk(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(
        ts=datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=i), open=o, high=h, low=l, close=c, volume=v
    )


def mk_signal(direction: fgt.TradeDirection, entry_price: float, stop_loss: float, take_profit: float, index: int = 10) -> sr.Signal:
    exit_plan = fgt.ExitPlan(
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profits=(take_profit,),
        risk_reward_ratio=abs(take_profit - entry_price) / abs(entry_price - stop_loss),
    )
    pivot = fgt.SwingPoint(index=index - 5, ts=mk(index - 5, 0, 0, 0, 0).ts, price=entry_price, direction=fgt.SwingDirection.LOW, wick_rejection_score=0.5)
    return sr.Signal(
        ts=mk(index, 0, 0, 0, 0).ts,
        index=index,
        pivot=pivot,
        basis_leg_start=pivot,
        direction=direction,
        entry_price=entry_price,
        exit_plan=exit_plan,
        confidence=0.7,
        structure_event=None,
    )


# --- simulate_trade ---


def test_simulate_trade_no_funding_events_net_equals_gross():
    signal = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=110.0, index=10)
    granular = [mk(11, 100, 111, 99, 110)]  # hits TP on the first candle
    trade = ts.simulate_trade(signal, granular, funding_events=[], max_holding_bars=5)
    assert trade.label.outcome is fgt.BarrierOutcome.TAKE_PROFIT
    assert trade.funding_cost_pct == pytest.approx(0.0)
    assert trade.funding_events_count == 0
    assert trade.net_return_pct == pytest.approx(trade.label.return_pct)


def test_simulate_trade_long_funding_cost_reduces_net_return():
    signal = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=110.0, index=10)
    granular = [mk(11, 100, 101, 99, 100.5), mk(12, 100.5, 111, 100, 110)]
    funding_events = [ts.FundingEvent(ts=mk(11, 0, 0, 0, 0).ts, rate=0.001)]
    trade = ts.simulate_trade(signal, granular, funding_events, max_holding_bars=5)
    assert trade.funding_cost_pct == pytest.approx(0.001)
    assert trade.net_return_pct == pytest.approx(trade.label.return_pct - 0.001)


def test_simulate_trade_short_funding_is_a_net_benefit_when_rate_positive():
    # positive funding_rate means longs pay shorts -- a SHORT position
    # RECEIVES funding when the rate is positive, so its net_return_pct
    # should be HIGHER than gross, not lower.
    signal = mk_signal(fgt.TradeDirection.SHORT, entry_price=100.0, stop_loss=105.0, take_profit=90.0, index=10)
    granular = [mk(11, 100, 101, 99, 99.5), mk(12, 99.5, 100, 89, 90)]
    funding_events = [ts.FundingEvent(ts=mk(11, 0, 0, 0, 0).ts, rate=0.001)]
    trade = ts.simulate_trade(signal, granular, funding_events, max_holding_bars=5)
    assert trade.funding_cost_pct == pytest.approx(-0.001)
    assert trade.net_return_pct == pytest.approx(trade.label.return_pct + 0.001)
    assert trade.net_return_pct > trade.label.return_pct


def test_simulate_trade_excludes_funding_events_outside_holding_window():
    signal = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=110.0, index=10)
    granular = [mk(11, 100, 111, 99, 110)]  # resolves on the first candle (bar 11)
    before_window = ts.FundingEvent(ts=mk(5, 0, 0, 0, 0).ts, rate=0.001)  # long before entry
    after_window = ts.FundingEvent(ts=mk(50, 0, 0, 0, 0).ts, rate=0.001)  # long after exit
    trade = ts.simulate_trade(signal, granular, [before_window, after_window], max_holding_bars=5)
    assert trade.funding_events_count == 0
    assert trade.funding_cost_pct == pytest.approx(0.0)


def test_simulate_trade_includes_funding_events_at_window_boundaries():
    signal = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=110.0, index=10)
    granular = [mk(11, 100, 101, 99, 100), mk(12, 100, 111, 99, 110)]  # resolves at bar 12
    at_entry = ts.FundingEvent(ts=signal.ts, rate=0.0005)
    at_exit_candle = mk(12, 100, 111, 99, 110)
    at_exit = ts.FundingEvent(ts=at_exit_candle.ts, rate=0.0005)
    trade = ts.simulate_trade(signal, granular, [at_entry, at_exit], max_holding_bars=5)
    assert trade.funding_events_count == 2
    assert trade.funding_cost_pct == pytest.approx(0.001)


def test_simulate_trade_sums_multiple_funding_events():
    signal = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=200.0, index=10)
    granular = [mk(11 + i, 100, 101, 99, 100) for i in range(4)] + [mk(15, 100, 210, 99, 200)]
    events = [ts.FundingEvent(ts=mk(11 + i, 0, 0, 0, 0).ts, rate=0.0002) for i in range(4)]
    trade = ts.simulate_trade(signal, granular, events, max_holding_bars=10)
    assert trade.funding_events_count == 4
    assert trade.funding_cost_pct == pytest.approx(0.0008)


def test_simulate_trade_preserves_censored_flag_from_label():
    signal = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=200.0, index=10)
    granular = [mk(11, 100, 101, 99, 100)]  # never resolves, runs out of data
    trade = ts.simulate_trade(signal, granular, [], max_holding_bars=5)
    assert trade.label.outcome is fgt.BarrierOutcome.TIMEOUT
    assert trade.label.censored is True


# --- fees (default 0.0, additive -- deep-dive F5) ---


def test_simulate_trade_defaults_fees_to_zero_no_behavior_change():
    signal = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=110.0, index=10)
    granular = [mk(11, 100, 111, 99, 110)]
    trade = ts.simulate_trade(signal, granular, funding_events=[], max_holding_bars=5)
    assert trade.fee_cost_pct == pytest.approx(0.0)
    assert trade.net_return_pct == pytest.approx(trade.label.return_pct)


def test_simulate_trade_fee_cost_is_sum_of_entry_and_exit_fractions():
    signal = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=110.0, index=10)
    granular = [mk(11, 100, 111, 99, 110)]
    trade = ts.simulate_trade(
        signal, granular, funding_events=[], max_holding_bars=5, fee_entry_fraction=0.0005, fee_exit_fraction=0.0005
    )
    assert trade.fee_cost_pct == pytest.approx(0.001)
    assert trade.net_return_pct == pytest.approx(trade.label.return_pct - 0.001)


def test_simulate_trade_fee_cost_is_direction_agnostic_unlike_funding():
    # a SHORT pays the same fee a LONG would -- fees don't flip sign by
    # direction the way funding_cost_pct does.
    signal = mk_signal(fgt.TradeDirection.SHORT, entry_price=100.0, stop_loss=105.0, take_profit=90.0, index=10)
    granular = [mk(11, 100, 101, 89, 90)]
    trade = ts.simulate_trade(
        signal, granular, funding_events=[], max_holding_bars=5, fee_entry_fraction=0.0005, fee_exit_fraction=0.0005
    )
    assert trade.fee_cost_pct == pytest.approx(0.001)
    assert trade.net_return_pct == pytest.approx(trade.label.return_pct - 0.001)


def test_simulate_trade_combines_funding_and_fee_costs():
    signal = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=110.0, index=10)
    granular = [mk(11, 100, 101, 99, 100.5), mk(12, 100.5, 111, 100, 110)]
    funding_events = [ts.FundingEvent(ts=mk(11, 0, 0, 0, 0).ts, rate=0.001)]
    trade = ts.simulate_trade(
        signal, granular, funding_events, max_holding_bars=5, fee_entry_fraction=0.0005, fee_exit_fraction=0.0005
    )
    assert trade.funding_cost_pct == pytest.approx(0.001)
    assert trade.fee_cost_pct == pytest.approx(0.001)
    assert trade.net_return_pct == pytest.approx(trade.label.return_pct - 0.001 - 0.001)


def test_simulate_trades_batch_passes_fee_fractions_through():
    signal = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=110.0, index=1)
    candles = [mk(i, 100, 111, 99, 110) for i in range(4)]
    trades = ts.simulate_trades(
        [signal], candles, funding_events=[], max_holding_bars=5, fee_entry_fraction=0.0005, fee_exit_fraction=0.0005
    )
    assert trades[0].fee_cost_pct == pytest.approx(0.001)


# --- simulate_trades (batch) ---


def test_simulate_trades_skips_signal_with_no_forward_candles():
    signal_a = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=110.0, index=1)
    signal_b = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=110.0, index=3)  # last candle
    candles = [mk(i, 100, 111, 99, 110) for i in range(4)]  # indices 0-3, signal_b has no candles[4:]
    trades = ts.simulate_trades([signal_a, signal_b], candles, funding_events=[], max_holding_bars=5)
    assert len(trades) == 1
    assert trades[0].signal_index == 1


def test_simulate_trades_processes_each_signal_independently():
    signal_a = mk_signal(fgt.TradeDirection.LONG, entry_price=100.0, stop_loss=95.0, take_profit=110.0, index=1)
    signal_b = mk_signal(fgt.TradeDirection.SHORT, entry_price=100.0, stop_loss=105.0, take_profit=90.0, index=1)
    candles = [mk(0, 100, 101, 99, 100), mk(1, 100, 101, 99, 100), mk(2, 100, 111, 99, 105)]
    trades = ts.simulate_trades([signal_a, signal_b], candles, funding_events=[], max_holding_bars=5)
    assert len(trades) == 2
    assert trades[0].direction is fgt.TradeDirection.LONG
    assert trades[0].label.outcome is fgt.BarrierOutcome.TAKE_PROFIT
    assert trades[1].direction is fgt.TradeDirection.SHORT
    assert trades[1].label.outcome is fgt.BarrierOutcome.STOP_LOSS
