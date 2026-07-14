import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import risk_gate as rg  # noqa: E402

OPEN_MANDATE = rg.RiskMandateSnapshot(kill_switch_active=False, symbol_universe=None)


def _evaluate(
    direction=rg.TradeDirection.LONG,
    entry_price=100.0,
    stop_loss=95.0,
    take_profit_1=110.0,
    risk_reward_ratio=2.0,
    instrument_symbol="BTCUSDT",
    mandate=OPEN_MANDATE,
    min_rr_threshold=rg.DEFAULT_MIN_RR_THRESHOLD,
):
    return rg.evaluate_risk_gate(
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        risk_reward_ratio=risk_reward_ratio,
        instrument_symbol=instrument_symbol,
        mandate=mandate,
        min_rr_threshold=min_rr_threshold,
    )


def test_all_pass_case():
    result = _evaluate()
    assert result.passed is True
    assert result.rejections == ()


def test_kill_switch_blocks():
    mandate = rg.RiskMandateSnapshot(kill_switch_active=True, symbol_universe=None)
    result = _evaluate(mandate=mandate)
    assert result.passed is False
    assert any("kill_switch_active" in r for r in result.rejections)


def test_symbol_universe_rejects_symbol_not_in_list():
    mandate = rg.RiskMandateSnapshot(kill_switch_active=False, symbol_universe=("ETHUSDT",))
    result = _evaluate(instrument_symbol="BTCUSDT", mandate=mandate)
    assert result.passed is False
    assert any("symbol_universe" in r for r in result.rejections)


def test_symbol_universe_passes_symbol_in_list():
    mandate = rg.RiskMandateSnapshot(kill_switch_active=False, symbol_universe=("BTCUSDT", "ETHUSDT"))
    result = _evaluate(instrument_symbol="BTCUSDT", mandate=mandate)
    assert result.passed is True


def test_symbol_universe_none_means_no_restriction():
    mandate = rg.RiskMandateSnapshot(kill_switch_active=False, symbol_universe=None)
    result = _evaluate(instrument_symbol="ANY_SYMBOL", mandate=mandate)
    assert result.passed is True


def test_rr_below_threshold_rejects():
    result = _evaluate(risk_reward_ratio=1.2)
    assert result.passed is False
    assert any("risk_reward_ratio" in r for r in result.rejections)


def test_missing_take_profit_or_rr_rejects():
    result = _evaluate(take_profit_1=None, risk_reward_ratio=None)
    assert result.passed is False
    assert any("no take_profit_1" in r for r in result.rejections)


def test_long_entry_not_between_sl_and_tp1_rejects():
    result = _evaluate(direction=rg.TradeDirection.LONG, entry_price=94.0, stop_loss=95.0, take_profit_1=110.0)
    assert result.passed is False
    assert any("LONG entry_price" in r for r in result.rejections)


def test_short_entry_not_between_tp1_and_sl_rejects():
    result = _evaluate(direction=rg.TradeDirection.SHORT, entry_price=96.0, stop_loss=95.0, take_profit_1=90.0)
    assert result.passed is False
    assert any("SHORT entry_price" in r for r in result.rejections)


def test_short_all_pass_case():
    result = _evaluate(direction=rg.TradeDirection.SHORT, entry_price=100.0, stop_loss=105.0, take_profit_1=90.0, risk_reward_ratio=2.0)
    assert result.passed is True


def test_multiple_failures_collects_all_rejections():
    mandate = rg.RiskMandateSnapshot(kill_switch_active=True, symbol_universe=("ETHUSDT",))
    result = _evaluate(instrument_symbol="BTCUSDT", mandate=mandate, risk_reward_ratio=1.0)
    assert result.passed is False
    assert len(result.rejections) > 1
