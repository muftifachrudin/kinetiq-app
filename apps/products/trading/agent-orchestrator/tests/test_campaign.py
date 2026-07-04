import datetime
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "validation" / "fib_gann_backtest"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import campaign  # noqa: E402
import derivatives_context as dc  # noqa: E402
import fib_gann_timing as fgt  # noqa: E402
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
    windows = campaign.exp.generate_windows_by_calendar(
        start=candles[0].ts, end=candles[-1].ts,
        train_months=campaign.exp.TRAIN_MONTHS, test_months=campaign.exp.TEST_MONTHS,
        embargo_days=campaign.exp.EMBARGO_DAYS, step_months=campaign.exp.STEP_MONTHS, mode=campaign.exp.WINDOW_MODE,
    )
    report = campaign.run_fit_report(candles, windows, [], campaign.exp.MAX_HOLDING_BARS)
    assert isinstance(report, campaign.FitReport)
    if report.median_auc is not None:
        assert 0.0 <= report.median_auc <= 1.0
    assert isinstance(report.adopted, bool)


def test_run_fit_report_not_adopted_when_no_windows():
    candles = noisy_zigzag()
    report = campaign.run_fit_report(candles, [], [], campaign.exp.MAX_HOLDING_BARS)
    assert report.median_auc is None
    assert report.adopted is False
