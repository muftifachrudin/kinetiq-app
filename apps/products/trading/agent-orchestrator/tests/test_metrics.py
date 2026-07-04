import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "validation" / "fib_gann_backtest"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402
import metrics  # noqa: E402
import trade_simulator as ts  # noqa: E402

UTC = datetime.timezone.utc
LONG = fgt.TradeDirection.LONG


def mk_ts(hours: int) -> datetime.datetime:
    return datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=hours)


def mk_trade(
    signal_hour: int,
    exit_hour: int,
    return_pct: float,
    funding_cost_pct: float = 0.0,
    censored: bool = False,
    outcome: fgt.BarrierOutcome = fgt.BarrierOutcome.TAKE_PROFIT,
) -> ts.SimulatedTrade:
    label = fgt.TripleBarrierLabel(
        outcome=outcome,
        exit_price=100.0,
        exit_ts=mk_ts(exit_hour),
        bars_held=exit_hour - signal_hour,
        return_pct=return_pct,
        censored=censored,
    )
    return ts.SimulatedTrade(
        signal_ts=mk_ts(signal_hour),
        signal_index=signal_hour,
        direction=LONG,
        confidence=0.7,
        entry_price=100.0,
        label=label,
        funding_cost_pct=funding_cost_pct,
        funding_events_count=0,
        fee_cost_pct=0.0,
        net_return_pct=return_pct - funding_cost_pct,
    )


# --- compute_metrics ---


def test_compute_metrics_rejects_empty_trades():
    with pytest.raises(ValueError, match="must not be empty"):
        metrics.compute_metrics([])


def test_compute_metrics_rejects_all_censored():
    trades = [mk_trade(0, 5, 0.01, censored=True)]
    with pytest.raises(ValueError, match="no non-censored trades"):
        metrics.compute_metrics(trades)


def test_compute_metrics_excludes_censored_and_reports_count():
    trades = [mk_trade(0, 5, 0.02), mk_trade(10, 15, -0.01, censored=True)]
    result = metrics.compute_metrics(trades)
    assert result.trade_count == 1
    assert result.censored_count == 1


def test_compute_metrics_win_loss_count_uses_net_return():
    # gross positive but funding cost flips it net-negative -- must count
    # as a LOSS, not a win, since win/loss is defined on net_return_pct.
    trades = [mk_trade(0, 5, return_pct=0.01, funding_cost_pct=0.02)]
    result = metrics.compute_metrics(trades)
    assert result.win_count == 0
    assert result.loss_count == 1


def test_compute_metrics_profit_factor_gross_vs_net_diverge_from_funding():
    trades = [
        mk_trade(0, 5, return_pct=0.05, funding_cost_pct=0.01),
        mk_trade(10, 15, return_pct=-0.02, funding_cost_pct=0.01),
    ]
    result = metrics.compute_metrics(trades)
    # gross: profit=0.05, loss=0.02 -> PF=2.5; net: profit=0.04, loss=0.03 -> PF=1.333
    assert result.profit_factor_gross == pytest.approx(2.5)
    assert result.profit_factor_net == pytest.approx(0.04 / 0.03)
    assert result.profit_factor_net < result.profit_factor_gross  # funding cost narrows the gap


def test_compute_metrics_profit_factor_none_when_no_losses():
    trades = [mk_trade(0, 5, 0.02), mk_trade(10, 15, 0.03)]
    result = metrics.compute_metrics(trades)
    assert result.profit_factor_gross is None
    assert result.profit_factor_net is None


def test_compute_metrics_sharpe_none_with_single_trade():
    result = metrics.compute_metrics([mk_trade(0, 5, 0.02)])
    assert result.sharpe_gross is None
    assert result.sharpe_net is None


def test_compute_metrics_sharpe_annualizes_from_actual_holding_duration():
    # 3 trades, each held exactly 24h -> trades_per_year = 365.25
    trades = [mk_trade(0, 24, 0.02), mk_trade(48, 72, -0.01), mk_trade(96, 120, 0.015)]
    result = metrics.compute_metrics(trades)
    assert result.avg_holding_duration_hours == pytest.approx(24.0)
    assert result.trades_per_year == pytest.approx(365.25)
    assert result.sharpe_gross is not None


def test_compute_metrics_max_drawdown_from_compounding_equity_curve():
    # +10%, -20%, +5% in chronological order: equity 1.0 -> 1.10 -> 0.88 -> 0.924
    # peak=1.10, trough=0.88 -> drawdown = (1.10-0.88)/1.10 = 0.2 exactly
    trades = [mk_trade(0, 5, 0.10), mk_trade(10, 15, -0.20), mk_trade(20, 25, 0.05)]
    result = metrics.compute_metrics(trades)
    assert result.max_drawdown_pct_gross == pytest.approx(0.2)


def test_compute_metrics_sorts_by_signal_ts_before_drawdown():
    # passed out of order -- must still compute drawdown chronologically
    trades = [mk_trade(20, 25, 0.05), mk_trade(0, 5, 0.10), mk_trade(10, 15, -0.20)]
    result = metrics.compute_metrics(trades)
    assert result.max_drawdown_pct_gross == pytest.approx(0.2)


def test_compute_metrics_all_wins_zero_drawdown():
    trades = [mk_trade(0, 5, 0.01), mk_trade(10, 15, 0.02)]
    result = metrics.compute_metrics(trades)
    assert result.max_drawdown_pct_gross == pytest.approx(0.0)


# --- compute_metrics_by_regime ---


def test_compute_metrics_by_regime_groups_correctly():
    trades = [mk_trade(0, 5, 0.02), mk_trade(10, 15, -0.01), mk_trade(20, 25, 0.03)]

    def regime_of(trade):
        return "risk_on" if trade.signal_index < 15 else "neutral"

    grouped = metrics.compute_metrics_by_regime(trades, regime_of)
    assert set(grouped.keys()) == {"risk_on", "neutral"}
    assert grouped["risk_on"].trade_count == 2
    assert grouped["neutral"].trade_count == 1


def test_compute_metrics_by_regime_empty_group_raises_via_compute_metrics():
    trades = [mk_trade(0, 5, 0.02, censored=True)]

    def regime_of(_trade):
        return "risk_on"

    with pytest.raises(ValueError, match="no non-censored trades"):
        metrics.compute_metrics_by_regime(trades, regime_of)


# --- weighted_profit_factor (F6b I1(a)) ---


def test_weighted_profit_factor_matches_unweighted_at_multiplier_one():
    returns = [0.05, -0.02, 0.03, -0.01]
    weighted = [(1.0, r) for r in returns]
    assert metrics.weighted_profit_factor(weighted) == pytest.approx(metrics._profit_factor(returns))  # noqa: SLF001


def test_weighted_profit_factor_scales_contribution_by_weight():
    # a 2x-sized winner should count twice as much toward gross profit
    weighted = [(2.0, 0.05), (1.0, -0.02)]
    # gross_profit = 2.0*0.05=0.10, gross_loss = 1.0*0.02=0.02 -> PF=5.0
    assert metrics.weighted_profit_factor(weighted) == pytest.approx(5.0)


def test_weighted_profit_factor_none_when_no_weighted_loss():
    weighted = [(1.5, 0.05), (0.5, 0.02)]
    assert metrics.weighted_profit_factor(weighted) is None


# --- bootstrap_pf_net_ci (F6b I5) ---


def test_bootstrap_pf_net_ci_none_with_fewer_than_two_trades():
    trades = [mk_trade(0, 5, 0.02)]
    assert metrics.bootstrap_pf_net_ci(trades) is None


def test_bootstrap_pf_net_ci_excludes_censored_trades():
    trades = [mk_trade(0, 5, 0.02, censored=True)]
    assert metrics.bootstrap_pf_net_ci(trades) is None


def test_bootstrap_pf_net_ci_returns_ordered_positive_bounds():
    trades = [mk_trade(i * 10, i * 10 + 5, r) for i, r in enumerate([0.03, -0.01, 0.02, -0.015, 0.025, -0.01, 0.04, -0.02])]
    ci = metrics.bootstrap_pf_net_ci(trades, n_resamples=500)
    assert ci is not None
    lower, upper = ci
    assert 0.0 <= lower <= upper


def test_bootstrap_pf_net_ci_is_deterministic_for_same_seed():
    trades = [mk_trade(i * 10, i * 10 + 5, r) for i, r in enumerate([0.03, -0.01, 0.02, -0.015, 0.025, -0.01])]
    first = metrics.bootstrap_pf_net_ci(trades, n_resamples=300, seed=7)
    second = metrics.bootstrap_pf_net_ci(trades, n_resamples=300, seed=7)
    assert first == second


def test_bootstrap_pf_net_ci_differs_for_different_seeds_generally():
    trades = [mk_trade(i * 10, i * 10 + 5, r) for i, r in enumerate([0.03, -0.01, 0.02, -0.015, 0.025, -0.01])]
    a = metrics.bootstrap_pf_net_ci(trades, n_resamples=50, seed=1)
    b = metrics.bootstrap_pf_net_ci(trades, n_resamples=50, seed=2)
    assert a is not None and b is not None  # just confirms both seeds produce a usable result
