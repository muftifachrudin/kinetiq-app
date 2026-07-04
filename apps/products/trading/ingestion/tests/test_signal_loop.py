"""Only pure/logic-only functions are covered here, same discipline as
test_ingest.py's own docstring: everything in signal_loop.py that touches a
real DB Session (load_candles/existing_signal_timestamps/persist_new_signals/
run_signal_loop_once) is verified manually against real Railway/Neon post-
deploy (see tools/railway_logs.py), not via pytest DB mocking."""

import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent-orchestrator", "skills", "strategy"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agent-orchestrator", "validation", "fib_gann_backtest"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "packages", "db", "src"))
import fib_gann_timing as fgt  # noqa: E402
import signal_loop  # noqa: E402
import signal_runner as sr  # noqa: E402
from kinetiq_db.models import RiskMandate  # noqa: E402

UTC = datetime.timezone.utc
LONG = fgt.TradeDirection.LONG


def mk_signal(entry_price: float = 100.0, stop_loss: float = 95.0, take_profits: tuple = (110.0,)) -> sr.Signal:
    exit_plan = fgt.ExitPlan(direction=LONG, entry_price=entry_price, stop_loss=stop_loss, take_profits=take_profits, risk_reward_ratio=2.0)
    pivot = fgt.SwingPoint(index=0, ts=datetime.datetime(2024, 1, 1, tzinfo=UTC), price=entry_price, direction=fgt.SwingDirection.LOW, wick_rejection_score=0.5)
    return sr.Signal(
        ts=datetime.datetime(2024, 1, 1, tzinfo=UTC), index=0, pivot=pivot, basis_leg_start=pivot, direction=LONG,
        entry_price=entry_price, exit_plan=exit_plan, confidence=0.7, structure_event=None,
    )


# --- representative account constants track RiskMandate's own defaults ---


def test_representative_risk_pct_matches_risk_mandate_server_default():
    assert signal_loop.REPRESENTATIVE_RISK_PCT_PER_TRADE == float(RiskMandate.__table__.c.risk_pct_per_trade.server_default.arg)


def test_representative_max_leverage_cap_matches_risk_mandate_server_default():
    assert signal_loop.REPRESENTATIVE_MAX_LEVERAGE_CAP == float(RiskMandate.__table__.c.max_leverage.server_default.arg)


# --- _representative_pre_trade_card ---


def test_representative_pre_trade_card_none_when_atr_missing():
    signal = mk_signal()
    assert signal_loop._representative_pre_trade_card(signal, None) is None  # noqa: SLF001
    assert signal_loop._representative_pre_trade_card(signal, 0.0) is None  # noqa: SLF001
    assert signal_loop._representative_pre_trade_card(signal, -1.0) is None  # noqa: SLF001


def test_representative_pre_trade_card_builds_for_a_normal_signal():
    signal = mk_signal(entry_price=100.0, stop_loss=95.0)
    card = signal_loop._representative_pre_trade_card(signal, atr_value=2.0)  # noqa: SLF001
    assert card is not None
    assert card["risk_amount_usd"] == signal_loop.REPRESENTATIVE_EQUITY_USD * signal_loop.REPRESENTATIVE_RISK_PCT_PER_TRADE
    assert card["leverage_used"] <= signal_loop.REPRESENTATIVE_MAX_LEVERAGE_CAP


def test_representative_pre_trade_card_none_when_entry_equals_stop_loss():
    # position_sizing.py's build_pre_trade_card raises ValueError when
    # entry_price == stop_loss (zero SL distance) -- a malformed exit_plan
    # that should never occur for a real signal_runner.Signal (its own
    # entry-validity gate rejects this), but defensively this function must
    # swallow it into None rather than letting one bad signal crash the
    # whole cycle's persistence for every other signal/instrument.
    signal = mk_signal(entry_price=100.0, stop_loss=100.0)
    card = signal_loop._representative_pre_trade_card(signal, atr_value=2.0)  # noqa: SLF001
    assert card is None


# --- _factor_scores ---


def test_factor_scores_includes_every_declared_field():
    signal = mk_signal()
    scores = signal_loop._factor_scores(signal, atr_value=2.0)  # noqa: SLF001
    for field in signal_loop.FACTOR_SCORE_FIELDS:
        assert field in scores
        assert scores[field] == getattr(signal, field)


def test_factor_scores_includes_daily_bias_alignment():
    # Regression test: FACTOR_SCORE_FIELDS was missing this field because
    # signal_loop.py (F0e P3, #85) merged before signal_runner.Signal grew
    # daily_bias_alignment (F6b PR-1, #86) -- production signals persisted
    # since then were silently missing this factor from factor_scores.
    signal = mk_signal()
    scores = signal_loop._factor_scores(signal, atr_value=2.0)  # noqa: SLF001
    assert scores["daily_bias_alignment"] == signal.daily_bias_alignment


def test_factor_scores_includes_config_label_and_pre_trade_card():
    signal = mk_signal()
    scores = signal_loop._factor_scores(signal, atr_value=2.0)  # noqa: SLF001
    assert scores["config_label"] == signal_loop.CONFIG_LABEL
    assert scores["pre_trade_card"] is not None


def test_factor_scores_pre_trade_card_none_when_atr_missing():
    signal = mk_signal()
    scores = signal_loop._factor_scores(signal, atr_value=None)  # noqa: SLF001
    assert scores["pre_trade_card"] is None
