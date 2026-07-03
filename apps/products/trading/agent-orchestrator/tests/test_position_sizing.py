import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "validation" / "fib_gann_backtest"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402
import position_sizing as ps  # noqa: E402
import trade_simulator as ts  # noqa: E402

LONG = fgt.TradeDirection.LONG
SHORT = fgt.TradeDirection.SHORT


def mk_exit_plan(direction, entry_price, stop_loss, take_profits=()) -> fgt.ExitPlan:
    risk = abs(entry_price - stop_loss)
    rr = abs(take_profits[0] - entry_price) / risk if take_profits and risk > 0 else None
    return fgt.ExitPlan(direction=direction, entry_price=entry_price, stop_loss=stop_loss, take_profits=take_profits, risk_reward_ratio=rr)


# entry=100, sl=95, atr=2.0 -> max_safe_leverage = 100/(5+2+0.4) = 100/7.4 = 13.513513...


def test_long_leverage_bound_by_structure_not_cap():
    exit_plan = mk_exit_plan(LONG, 100.0, 95.0, (115.0,))
    card = ps.build_pre_trade_card(exit_plan, atr_value=2.0, equity_usd=10_000, risk_pct_per_trade=0.01, margin_mode=ts.MarginMode.ISOLATED, max_leverage_cap=50.0)

    assert card.risk_amount_usd == pytest.approx(100.0)
    assert card.qty == pytest.approx(20.0)
    assert card.notional_usd == pytest.approx(2000.0)
    assert card.max_safe_leverage == pytest.approx(100.0 / 7.4)
    assert card.leverage_used == pytest.approx(100.0 / 7.4)  # capped by structure, not the 50x mandate cap
    assert card.initial_margin_usd == pytest.approx(148.0)
    assert card.est_liquidation_price == pytest.approx(93.0)
    assert card.margin_ratio_at_entry == pytest.approx(0.004 / 0.074)
    assert card.sl_distance_pct_notional == pytest.approx(0.05)
    assert card.sl_distance_pct_margin == pytest.approx(5.0 / 7.4)
    assert card.tp1_distance_pct_notional == pytest.approx(0.15)
    assert card.tp1_distance_pct_margin == pytest.approx(0.15 * 100.0 / 7.4)
    assert any("below max_leverage_cap" in w for w in card.warnings)


def test_long_leverage_bound_by_mandate_cap():
    exit_plan = mk_exit_plan(LONG, 100.0, 95.0, (115.0,))
    card = ps.build_pre_trade_card(exit_plan, atr_value=2.0, equity_usd=10_000, risk_pct_per_trade=0.01, margin_mode=ts.MarginMode.ISOLATED, max_leverage_cap=5.0)

    assert card.max_safe_leverage == pytest.approx(100.0 / 7.4)  # unchanged -- a structural property of entry/SL/ATR
    assert card.leverage_used == pytest.approx(5.0)  # capped by the mandate this time
    assert card.initial_margin_usd == pytest.approx(400.0)
    assert card.est_liquidation_price == pytest.approx(80.4)
    assert not any("below max_leverage_cap" in w for w in card.warnings)  # cap is the binding constraint here, not structure


def test_short_symmetric_to_long():
    exit_plan = mk_exit_plan(SHORT, 100.0, 105.0, (85.0,))
    card = ps.build_pre_trade_card(exit_plan, atr_value=2.0, equity_usd=10_000, risk_pct_per_trade=0.01, margin_mode=ts.MarginMode.ISOLATED, max_leverage_cap=50.0)

    assert card.leverage_used == pytest.approx(100.0 / 7.4)
    assert card.initial_margin_usd == pytest.approx(148.0)
    assert card.est_liquidation_price == pytest.approx(107.0)  # above entry for a SHORT
    assert card.sl_distance_pct_notional == pytest.approx(0.05)
    assert card.tp1_distance_pct_notional == pytest.approx(0.15)


def test_no_take_profits_leaves_tp1_fields_none():
    exit_plan = mk_exit_plan(LONG, 100.0, 95.0, ())
    card = ps.build_pre_trade_card(exit_plan, atr_value=2.0, equity_usd=10_000, risk_pct_per_trade=0.01, margin_mode=ts.MarginMode.ISOLATED, max_leverage_cap=50.0)

    assert card.tp1_distance_pct_notional is None
    assert card.tp1_distance_pct_margin is None


def test_cross_margin_mode_raises_not_implemented():
    exit_plan = mk_exit_plan(LONG, 100.0, 95.0, (115.0,))
    with pytest.raises(NotImplementedError, match="F7b"):
        ps.build_pre_trade_card(exit_plan, atr_value=2.0, equity_usd=10_000, risk_pct_per_trade=0.01, margin_mode=ts.MarginMode.CROSS, max_leverage_cap=50.0)


def test_free_balance_warning_fires_when_margin_exceeds_it():
    exit_plan = mk_exit_plan(LONG, 100.0, 95.0, (115.0,))
    card = ps.build_pre_trade_card(
        exit_plan,
        atr_value=2.0,
        equity_usd=10_000,
        risk_pct_per_trade=0.01,
        margin_mode=ts.MarginMode.ISOLATED,
        max_leverage_cap=50.0,
        free_balance_usd=100.0,  # initial_margin_usd is 148.0, exceeds this
    )
    assert any("exceeds the supplied free_balance_usd" in w for w in card.warnings)


def test_high_vol_flag_shrinks_risk_only_never_leverage_cap():
    exit_plan = mk_exit_plan(LONG, 100.0, 95.0, (115.0,))
    normal = ps.build_pre_trade_card(exit_plan, atr_value=2.0, equity_usd=10_000, risk_pct_per_trade=0.01, margin_mode=ts.MarginMode.ISOLATED, max_leverage_cap=50.0)
    high_vol = ps.build_pre_trade_card(
        exit_plan, atr_value=2.0, equity_usd=10_000, risk_pct_per_trade=0.01, margin_mode=ts.MarginMode.ISOLATED, max_leverage_cap=50.0, high_vol_flag=True
    )
    assert high_vol.risk_amount_usd == pytest.approx(normal.risk_amount_usd * ps.HIGH_VOL_RISK_MULTIPLIER)
    assert high_vol.qty < normal.qty
    assert high_vol.leverage_used == normal.leverage_used  # structural leverage bound is unaffected by risk sizing


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"equity_usd": 0.0}, "equity_usd must be positive"),
        ({"risk_pct_per_trade": 0.0}, "risk_pct_per_trade must be positive"),
        ({"max_leverage_cap": 0.0}, "max_leverage_cap must be positive"),
    ],
)
def test_rejects_non_positive_inputs(kwargs, match):
    exit_plan = mk_exit_plan(LONG, 100.0, 95.0, (115.0,))
    base = dict(atr_value=2.0, equity_usd=10_000, risk_pct_per_trade=0.01, margin_mode=ts.MarginMode.ISOLATED, max_leverage_cap=50.0)
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        ps.build_pre_trade_card(exit_plan, **base)


def test_rejects_stop_loss_equal_to_entry_price():
    exit_plan = mk_exit_plan(LONG, 100.0, 100.0, (115.0,))
    with pytest.raises(ValueError, match="stop_loss must differ"):
        ps.build_pre_trade_card(exit_plan, atr_value=2.0, equity_usd=10_000, risk_pct_per_trade=0.01, margin_mode=ts.MarginMode.ISOLATED, max_leverage_cap=50.0)
