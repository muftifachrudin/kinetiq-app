import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "validation" / "fib_gann_backtest"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402
import signal_runner as sr  # noqa: E402
import shadow_pair as sp  # noqa: E402
import trade_simulator as ts  # noqa: E402

UTC = datetime.timezone.utc
LONG = fgt.TradeDirection.LONG
SHORT = fgt.TradeDirection.SHORT


def mk_pivot(price: float, direction: fgt.SwingDirection = fgt.SwingDirection.LOW) -> fgt.SwingPoint:
    return fgt.SwingPoint(index=0, ts=datetime.datetime(2024, 1, 1, tzinfo=UTC), price=price, direction=direction, wick_rejection_score=0.8)


def mk_signal(ts_: datetime.datetime, direction: fgt.TradeDirection, entry_price: float, stop_loss: float, take_profit: float) -> sr.Signal:
    exit_plan = fgt.ExitPlan(
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profits=(take_profit,),
        risk_reward_ratio=abs(take_profit - entry_price) / abs(entry_price - stop_loss),
    )
    return sr.Signal(
        ts=ts_,
        index=0,
        pivot=mk_pivot(stop_loss),
        basis_leg_start=mk_pivot(entry_price, direction=fgt.SwingDirection.HIGH),
        direction=direction,
        entry_price=entry_price,
        exit_plan=exit_plan,
        confidence=0.8,
        structure_event=None,
    )


def mk_margin_context(leverage: float, margin_mode: ts.MarginMode = ts.MarginMode.ISOLATED) -> ts.MarginContext:
    return ts.build_margin_context(100.0, LONG, leverage, margin_mode)


def mk_sim(
    exit_reason: ts.ExitReason,
    exit_price: float,
    notional_return_pct: float,
    margin_return_pct: float,
    leverage: float = 10.0,
    exit_ts: datetime.datetime = datetime.datetime(2024, 1, 1, 5, tzinfo=UTC),
) -> ts.LeveragedTradeResult:
    return ts.LeveragedTradeResult(
        exit_reason=exit_reason,
        exit_price=exit_price,
        exit_ts=exit_ts,
        bars_held=5,
        notional_return_pct=notional_return_pct,
        margin_return_pct=margin_return_pct,
        censored=False,
        margin_context=mk_margin_context(leverage),
    )


def mk_real(
    ts_: datetime.datetime,
    direction: fgt.TradeDirection,
    entry_fill_price: float,
    exit_fill_price: float,
    leverage: float | None = None,
    exit_reason_real: str | None = None,
    fees_paid_usd: float | None = None,
    funding_paid_usd: float | None = None,
    notional_usd: float | None = None,
) -> sp.RealTrade:
    return sp.RealTrade(
        ts=ts_,
        direction=direction,
        entry_fill_price=entry_fill_price,
        exit_fill_price=exit_fill_price,
        leverage=leverage,
        exit_reason_real=exit_reason_real,
        fees_paid_usd=fees_paid_usd,
        funding_paid_usd=funding_paid_usd,
        notional_usd=notional_usd,
    )


SIGNAL_TS = datetime.datetime(2024, 1, 1, 0, tzinfo=UTC)


# --- real_trade_from_annotation_row ---


def test_real_trade_from_annotation_row_maps_fields():
    row = {
        "ts": SIGNAL_TS,
        "action": "long",
        "entry_fill_price": 100.5,
        "exit_fill_price": 105.0,
        "leverage": 10.0,
        "margin_mode": "isolated",
        "exit_reason_real": "take_profit",
        "fees_paid_usd": 1.2,
        "funding_paid_usd": 0.3,
    }
    real = sp.real_trade_from_annotation_row(row, notional_usd=1000.0)
    assert real.direction is LONG
    assert real.entry_fill_price == pytest.approx(100.5)
    assert real.leverage == pytest.approx(10.0)
    assert real.notional_usd == pytest.approx(1000.0)


def test_real_trade_from_annotation_row_rejects_missing_exit_fill():
    row = {"ts": SIGNAL_TS, "action": "long", "entry_fill_price": 100.0, "exit_fill_price": None}
    with pytest.raises(ValueError, match="not a completed round-trip"):
        sp.real_trade_from_annotation_row(row)


# --- match_signal_to_trade ---


def test_match_signal_to_trade_picks_nearest_same_direction_within_tolerance():
    s1 = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    s2 = mk_signal(SIGNAL_TS + datetime.timedelta(minutes=90), LONG, 101.0, 96.0, 111.0)
    s_wrong_direction = mk_signal(SIGNAL_TS + datetime.timedelta(minutes=5), SHORT, 100.0, 105.0, 90.0)
    real = mk_real(SIGNAL_TS + datetime.timedelta(minutes=100), LONG, 101.2, 108.0)
    match = sp.match_signal_to_trade([s1, s2, s_wrong_direction], real, tolerance=datetime.timedelta(hours=2))
    assert match is s2  # nearer in time than s1, and s_wrong_direction is excluded by direction


def test_match_signal_to_trade_returns_none_when_no_candidate_in_tolerance():
    s1 = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    real = mk_real(SIGNAL_TS + datetime.timedelta(hours=5), LONG, 101.0, 108.0)
    assert sp.match_signal_to_trade([s1], real, tolerance=datetime.timedelta(hours=1)) is None


# --- compute_divergence_attribution: entry_slippage ---


def test_entry_slippage_is_negative_when_long_pays_more_than_signal():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(SIGNAL_TS, LONG, 101.0, 110.0, exit_reason_real="take_profit")  # paid MORE than signal price -- bad for a long
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert attribution.entry_slippage_pct < 0.0


def test_entry_slippage_is_positive_when_long_pays_less_than_signal():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(SIGNAL_TS, LONG, 99.0, 110.0, exit_reason_real="take_profit")  # paid LESS -- good for a long
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert attribution.entry_slippage_pct > 0.0


def test_entry_slippage_sign_flips_for_short():
    signal = mk_signal(SIGNAL_TS, SHORT, 100.0, 105.0, 90.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 90.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(SIGNAL_TS, SHORT, 101.0, 90.0, exit_reason_real="take_profit")  # sold HIGHER than signal -- good for a short
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert attribution.entry_slippage_pct > 0.0


def test_entry_slippage_always_computable_even_without_leverage_or_exit_reason():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(SIGNAL_TS, LONG, 101.0, 110.0)  # no leverage, no exit_reason_real -- matches most of the 276 bulk-imported rows
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert isinstance(attribution.entry_slippage_pct, float)
    assert attribution.gap_margin_pct is None
    assert attribution.size_leverage_effect_pct is None
    assert attribution.exit_slippage_pct is None
    assert attribution.manual_override_pct is None
    assert attribution.residual_pct is None


# --- exit_slippage / manual_override ---


def test_exit_slippage_computed_when_exit_reason_matches():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(SIGNAL_TS, LONG, 100.0, 111.0, leverage=10.0, exit_reason_real="take_profit")  # exited a bit higher than sim
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert attribution.exit_reason_match is True
    assert attribution.exit_slippage_pct > 0.0  # better exit than sim assumed -- benefit
    assert attribution.manual_override_pct == pytest.approx(0.0)


def test_manual_override_captures_exit_price_gap_when_reason_differs_and_not_liquidated():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TIMEOUT, 103.0, 0.03, 0.3, leverage=10.0)
    real = mk_real(SIGNAL_TS, LONG, 100.0, 108.0, leverage=10.0, exit_reason_real="manual_override")
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert attribution.exit_reason_match is False
    assert attribution.exit_slippage_pct is None
    assert attribution.manual_override_pct is not None
    assert attribution.manual_override_pct > 0.0  # exited higher than sim's timeout price -- founder's discretionary exit helped here


def test_liquidation_mismatch_is_not_mislabeled_as_manual_override():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.STOP_LOSS, 95.0, -0.05, -0.5, leverage=10.0)
    real = mk_real(SIGNAL_TS, LONG, 100.0, 92.0, exit_reason_real="liquidated")  # real got liquidated, sim just hit SL
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert attribution.exit_reason_match is False
    assert attribution.manual_override_pct == pytest.approx(0.0)  # NOT the price gap -- this is a leverage effect, not discretion
    assert attribution.exit_slippage_pct is None


# --- size_leverage_effect / liquidation ---


def test_size_leverage_effect_captures_liquidation_even_without_known_real_leverage():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.STOP_LOSS, 95.0, -0.05, -0.5, leverage=10.0)  # sim only lost 50% margin (hit structural SL)
    real = mk_real(SIGNAL_TS, LONG, 100.0, 92.0, exit_reason_real="liquidated")  # real got wiped out, leverage itself unknown
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert attribution.size_leverage_effect_pct == pytest.approx(-1.0 - (-0.5))  # -100% vs sim's -50%
    assert attribution.gap_margin_pct == pytest.approx(-1.0 - (-0.5))


def test_size_leverage_effect_reflects_different_leverage_same_price_path():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)  # sim: 10x * 10% = 100% margin gain
    real = mk_real(SIGNAL_TS, LONG, 100.0, 110.0, leverage=5.0, exit_reason_real="take_profit")  # real used HALF the leverage
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    # counterfactual real margin pnl at sim's own price move (10%) but real's 5x leverage = 50%, vs sim's 100%
    assert attribution.size_leverage_effect_pct == pytest.approx(0.50 - 1.0)


def test_size_leverage_effect_none_when_real_leverage_unknown_and_not_liquidated():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(SIGNAL_TS, LONG, 100.0, 110.0, exit_reason_real="take_profit")  # no leverage recorded
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert attribution.size_leverage_effect_pct is None
    assert attribution.gap_margin_pct is None


# --- fees_funding_delta ---


def test_fees_funding_delta_none_without_notional_usd():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(SIGNAL_TS, LONG, 100.0, 110.0, leverage=10.0, exit_reason_real="take_profit", fees_paid_usd=5.0)
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert attribution.fees_funding_delta_pct is None


def test_fees_funding_delta_is_a_cost_when_notional_usd_given():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(
        SIGNAL_TS, LONG, 100.0, 110.0, leverage=10.0, exit_reason_real="take_profit",
        fees_paid_usd=5.0, funding_paid_usd=2.0, notional_usd=1000.0,
    )
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    # (5+2)/1000 * 10x leverage = 0.07, always a cost -> negative
    assert attribution.fees_funding_delta_pct == pytest.approx(-0.07)


# --- residual ---


def test_residual_is_none_when_any_component_missing():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(SIGNAL_TS, LONG, 100.0, 110.0, leverage=10.0, exit_reason_real="take_profit")  # no notional_usd -> fees None
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert attribution.residual_pct is None


def test_residual_is_near_zero_when_real_matches_sim_exactly():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(
        SIGNAL_TS, LONG, 100.0, 110.0, leverage=10.0, exit_reason_real="take_profit",
        fees_paid_usd=0.0, funding_paid_usd=0.0, notional_usd=1000.0,
    )
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert attribution.residual_pct == pytest.approx(0.0, abs=1e-9)


# --- timing_deviation ---


def test_timing_deviation_is_informational_duration():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(SIGNAL_TS + datetime.timedelta(minutes=45), LONG, 100.0, 110.0)
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    assert attribution.timing_deviation == datetime.timedelta(minutes=45)


# --- compute_fidelity_score ---


def test_fidelity_score_is_100_when_everything_matches_exactly():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(
        SIGNAL_TS, LONG, 100.0, 110.0, leverage=10.0, exit_reason_real="take_profit",
        fees_paid_usd=0.0, funding_paid_usd=0.0, notional_usd=1000.0,
    )
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    score = sp.compute_fidelity_score(attribution, risk_pct_per_trade=0.01)
    assert score == pytest.approx(100.0)


def test_fidelity_score_drops_with_large_manual_override():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TIMEOUT, 103.0, 0.03, 0.3, leverage=10.0)
    real = mk_real(SIGNAL_TS, LONG, 100.0, 120.0, leverage=10.0, exit_reason_real="manual_override")
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    score = sp.compute_fidelity_score(attribution, risk_pct_per_trade=0.01)
    assert score < 100.0


def test_fidelity_score_skips_missing_components_instead_of_penalizing():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(SIGNAL_TS, LONG, 100.0, 110.0)  # no leverage, no exit_reason_real, no notional -- like a bulk-imported row
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    score = sp.compute_fidelity_score(attribution, risk_pct_per_trade=0.01)
    assert score == pytest.approx(100.0)  # entry_slippage_pct is 0.0 here (real entry == signal entry), nothing else counted


def test_fidelity_score_rejects_non_positive_risk_pct():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(SIGNAL_TS, LONG, 100.0, 110.0)
    attribution = sp.compute_divergence_attribution(signal, sim, real)
    with pytest.raises(ValueError, match="must be positive"):
        sp.compute_fidelity_score(attribution, risk_pct_per_trade=0.0)


# --- build_shadow_pair ---


def test_build_shadow_pair_assembles_all_pieces():
    signal = mk_signal(SIGNAL_TS, LONG, 100.0, 95.0, 110.0)
    sim = mk_sim(ts.ExitReason.TAKE_PROFIT, 110.0, 0.10, 1.0, leverage=10.0)
    real = mk_real(
        SIGNAL_TS, LONG, 100.0, 110.0, leverage=10.0, exit_reason_real="take_profit",
        fees_paid_usd=0.0, funding_paid_usd=0.0, notional_usd=1000.0,
    )
    pair = sp.build_shadow_pair(signal, sim, real, risk_pct_per_trade=0.01)
    assert pair.signal is signal
    assert pair.sim is sim
    assert pair.real is real
    assert pair.fidelity_score == pytest.approx(100.0)
    assert pair.attribution.residual_pct == pytest.approx(0.0, abs=1e-9)
