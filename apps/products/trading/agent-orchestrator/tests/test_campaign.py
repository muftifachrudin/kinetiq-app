import datetime
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "validation" / "fib_gann_backtest"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import campaign  # noqa: E402
import derivatives_context as dc  # noqa: E402
import fib_gann_timing as fgt  # noqa: E402
import signal_runner as sr  # noqa: E402
import trade_simulator as ts  # noqa: E402

UTC = datetime.timezone.utc


def ts_at(hours: int) -> datetime.datetime:
    return datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=hours)


def mk(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(ts=ts_at(i), open=o, high=h, low=l, close=c, volume=v)


def noisy_zigzag(n: int = 1680, seed: int = 42) -> list[fgt.Candle]:
    """~70 days of hourly data -- same shape/rationale as
    test_rr_sl_experiment.py's own fixture (enough calendar span for >=1
    full walk-forward window, fast enough for O(n^2) generate_signals)."""
    rng = random.Random(seed)
    candles = []
    price = 100.0
    direction = -1
    for i in range(n):
        if i % 15 == 0:
            direction *= -1
        price += direction * rng.uniform(0.5, 2.0)
        o = price
        c = price + rng.uniform(-0.3, 0.3)
        h = max(o, c) + rng.uniform(0, 0.3)
        low = min(o, c) - rng.uniform(0, 0.3)
        candles.append(mk(i, o, h, low, c, v=100 + rng.uniform(-10, 10)))
        price = c
    return candles


def mk_trade(signal_ts: datetime.datetime, return_pct: float = 0.01) -> ts.SimulatedTrade:
    label = fgt.TripleBarrierLabel(outcome=fgt.BarrierOutcome.TAKE_PROFIT, exit_price=100.0, exit_ts=signal_ts + datetime.timedelta(hours=5), bars_held=5, return_pct=return_pct, censored=False)
    return ts.SimulatedTrade(
        signal_ts=signal_ts, signal_index=0, direction=fgt.TradeDirection.LONG, confidence=0.5, entry_price=100.0,
        label=label, funding_cost_pct=0.0, funding_events_count=0, fee_cost_pct=0.0, net_return_pct=return_pct,
    )


# --- monthly_drift / classify_regime / regime_of_trade ---


def test_monthly_drift_computes_first_open_to_last_close_per_month():
    candles = [
        fgt.Candle(ts=datetime.datetime(2024, 1, 1, tzinfo=UTC), open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0),
        fgt.Candle(ts=datetime.datetime(2024, 1, 15, tzinfo=UTC), open=100.0, high=111.0, low=99.0, close=110.0, volume=1.0),
        fgt.Candle(ts=datetime.datetime(2024, 2, 1, tzinfo=UTC), open=120.0, high=121.0, low=119.0, close=120.0, volume=1.0),
    ]
    drift = campaign.monthly_drift(candles)
    assert drift[(2024, 1)] == (110.0 - 100.0) / 100.0
    assert drift[(2024, 2)] == (120.0 - 120.0) / 120.0


def test_classify_regime_bull_bear_range():
    assert campaign.classify_regime(0.10) == "bull"
    assert campaign.classify_regime(-0.10) == "bear"
    assert campaign.classify_regime(0.0) == "range"
    assert campaign.classify_regime(campaign.BULL_DRIFT_THRESHOLD) == "range"  # boundary is exclusive
    assert campaign.classify_regime(campaign.BULL_DRIFT_THRESHOLD + 0.001) == "bull"


def test_regime_of_trade_looks_up_signal_month():
    trade = mk_trade(datetime.datetime(2024, 3, 15, tzinfo=UTC))
    drift_by_month = {(2024, 3): 0.10, (2024, 4): -0.10}
    assert campaign.regime_of_trade(trade, drift_by_month) == "bull"


def test_regime_of_trade_unknown_when_month_not_covered():
    trade = mk_trade(datetime.datetime(2025, 1, 1, tzinfo=UTC))
    assert campaign.regime_of_trade(trade, {}) == "unknown"


# --- direction_of_trade / direction_regime_breakdown (F6b I2) ---


def mk_trade_dir(signal_ts: datetime.datetime, direction: fgt.TradeDirection, return_pct: float = 0.01, censored: bool = False) -> ts.SimulatedTrade:
    label = fgt.TripleBarrierLabel(
        outcome=fgt.BarrierOutcome.TAKE_PROFIT, exit_price=100.0, exit_ts=signal_ts + datetime.timedelta(hours=5), bars_held=5, return_pct=return_pct, censored=censored
    )
    return ts.SimulatedTrade(
        signal_ts=signal_ts, signal_index=0, direction=direction, confidence=0.5, entry_price=100.0,
        label=label, funding_cost_pct=0.0, funding_events_count=0, fee_cost_pct=0.0, net_return_pct=return_pct,
    )


def test_direction_of_trade_maps_long_short():
    long_trade = mk_trade_dir(ts_at(0), fgt.TradeDirection.LONG)
    short_trade = mk_trade_dir(ts_at(0), fgt.TradeDirection.SHORT)
    assert campaign.direction_of_trade(long_trade) == "long"
    assert campaign.direction_of_trade(short_trade) == "short"


def test_direction_regime_breakdown_groups_by_direction_and_regime():
    bull_month = datetime.datetime(2024, 3, 15, tzinfo=UTC)
    bear_month = datetime.datetime(2024, 4, 15, tzinfo=UTC)
    drift_by_month = {(2024, 3): 0.10, (2024, 4): -0.10}
    trades = [
        mk_trade_dir(bull_month, fgt.TradeDirection.LONG, 0.02),
        mk_trade_dir(bull_month, fgt.TradeDirection.SHORT, -0.01),
        mk_trade_dir(bear_month, fgt.TradeDirection.SHORT, 0.03),
        mk_trade_dir(bear_month, fgt.TradeDirection.LONG, -0.02),
    ]
    breakdown = campaign.direction_regime_breakdown(trades, drift_by_month)
    assert set(breakdown.keys()) == {("long", "bull"), ("short", "bull"), ("short", "bear"), ("long", "bear")}
    assert breakdown[("long", "bull")].trade_count == 1


def test_direction_regime_breakdown_excludes_all_censored_groups():
    trades = [mk_trade_dir(ts_at(0), fgt.TradeDirection.LONG, 0.02, censored=True)]
    breakdown = campaign.direction_regime_breakdown(trades, {})
    assert breakdown == {}


# --- CAMPAIGN_CONFIGS ---


def test_campaign_configs_covers_baseline_and_f5_candidate():
    names = {c.name for c in campaign.CAMPAIGN_CONFIGS}
    assert names == {"current_defaults", "f5_candidate"}


def test_current_defaults_config_matches_production_defaults():
    baseline = next(c for c in campaign.CAMPAIGN_CONFIGS if c.name == "current_defaults")
    assert baseline.min_rr_threshold == fgt.DEFAULT_MIN_RR_THRESHOLD
    assert baseline.max_rr_threshold is None
    assert baseline.sl_atr_buffer_multiplier == fgt.DEFAULT_SL_ATR_BUFFER_MULTIPLIER


def test_f5_candidate_config_matches_fase5_recommendation():
    candidate = next(c for c in campaign.CAMPAIGN_CONFIGS if c.name == "f5_candidate")
    assert candidate.min_rr_threshold == 2.0
    assert candidate.max_rr_threshold == 5.0
    assert candidate.sl_atr_buffer_multiplier == 1.0


# --- run_series_campaign (end-to-end, synthetic data) ---


def test_run_series_campaign_returns_well_formed_result():
    candles = noisy_zigzag()
    config = campaign.CAMPAIGN_CONFIGS[0]
    result = campaign.run_series_campaign("synthetic", candles, config)
    assert result.series == "synthetic"
    assert result.config_name == config.name
    assert result.total_windows >= 1
    assert 0 <= result.windows_passing_pf <= result.total_windows
    assert isinstance(result.promoted, bool)
    assert isinstance(result.fit_report, campaign.FitReport)
    if result.pooled_pf_net_ci90 is not None:
        lower, upper = result.pooled_pf_net_ci90
        assert lower <= upper
    assert isinstance(result.direction_regime_metrics, dict)
    for key in result.direction_regime_metrics:
        assert key[0] in {"long", "short"}


def test_run_series_campaign_promoted_matches_pass_fraction():
    candles = noisy_zigzag()
    result = campaign.run_series_campaign("synthetic", candles, campaign.CAMPAIGN_CONFIGS[0])
    if result.total_windows == 0:
        assert result.promoted is False
    else:
        expected = (result.windows_passing_pf / result.total_windows) >= campaign.PF_PASS_FRACTION
        assert result.promoted == expected


def test_run_series_campaign_wires_derivatives_records():
    candles = noisy_zigzag()
    base_date = candles[0].ts.date()
    records = [
        dc.DailyDerivativesRecord(
            date=base_date - datetime.timedelta(days=400 - i),
            price_close=100.0 + i,
            oi_close=1000.0 + i,
            funding_rate=0.0001 * i,
            global_ls_ratio=1.0,
            top_ls_ratio=1.0,
        )
        for i in range(400)
    ]
    without = campaign.run_series_campaign("synthetic", candles, campaign.CAMPAIGN_CONFIGS[0])
    with_derivatives = campaign.run_series_campaign("synthetic", candles, campaign.CAMPAIGN_CONFIGS[0], derivatives_records=records)
    # same gates (min/max rr, sl) -> same signal COUNT either way (derivatives
    # fields don't change which signals pass R:R/entry gates), but this at
    # least confirms the derivatives-aware path runs without crashing and
    # produces an equally well-formed result.
    assert with_derivatives.total_signals == without.total_signals
    assert with_derivatives.total_windows == without.total_windows


# --- run_fit_report ---


def test_run_fit_report_returns_well_formed_result():
    candles = noisy_zigzag()
    signals = sr.generate_signals(candles)
    windows = campaign.exp.generate_windows_by_calendar(
        start=candles[0].ts, end=candles[-1].ts,
        train_months=campaign.exp.TRAIN_MONTHS, test_months=campaign.exp.TEST_MONTHS,
        embargo_days=campaign.exp.EMBARGO_DAYS, step_months=campaign.exp.STEP_MONTHS, mode=campaign.exp.WINDOW_MODE,
    )
    report = campaign.run_fit_report(signals, candles, windows, [], campaign.exp.MAX_HOLDING_BARS)
    assert isinstance(report, campaign.FitReport)
    if report.median_auc is not None:
        assert 0.0 <= report.median_auc <= 1.0
    assert isinstance(report.adopted, bool)


def test_run_fit_report_not_adopted_when_no_windows():
    candles = noisy_zigzag()
    signals = sr.generate_signals(candles)
    report = campaign.run_fit_report(signals, candles, [], [], campaign.exp.MAX_HOLDING_BARS)
    assert report.median_auc is None
    assert report.adopted is False


def test_run_fit_report_uses_supplied_signals_derivatives_fields_not_neutral_defaults():
    # Regression test for the bug this function's docstring describes:
    # it must fit against the SUPPLIED signals (with real derivatives
    # fields, when the caller generated them that way), not silently
    # regenerate a fresh, derivatives-blind signal set of its own.
    candles = noisy_zigzag()
    base_date = candles[0].ts.date()
    records = [
        dc.DailyDerivativesRecord(
            date=base_date - datetime.timedelta(days=400 - i),
            price_close=100.0 + i, oi_close=1000.0 + i, funding_rate=0.0001 * i,
            global_ls_ratio=1.0, top_ls_ratio=1.0,
        )
        for i in range(400)
    ]
    signals = sr.generate_signals(candles, derivatives_records=records)
    assert any(s.funding_contrarian_alignment != 0.5 for s in signals)  # sanity: derivatives fields are real, not all-neutral

    labeled = campaign.fw.build_labeled_signals(signals, candles, [], campaign.exp.MAX_HOLDING_BARS)
    # at least one non-neutral derivatives value must actually reach the labeled set used for fitting
    assert any(ls.signal.funding_contrarian_alignment != 0.5 for ls in labeled)
