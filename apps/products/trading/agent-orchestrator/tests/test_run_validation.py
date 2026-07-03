import datetime
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "validation" / "fib_gann_backtest"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import fib_gann_timing as fgt  # noqa: E402
import metrics  # noqa: E402
import run_validation as rv  # noqa: E402
from kinetiq_backtest.types import WalkForwardWindow  # noqa: E402

UTC = datetime.timezone.utc


def ts_at(hours: int) -> datetime.datetime:
    return datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=hours)


def mk(i: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> fgt.Candle:  # noqa: E741
    return fgt.Candle(ts=ts_at(i), open=o, high=h, low=l, close=c, volume=v)


def window(window_id, train_start_h, train_end_h, test_start_h, test_end_h) -> WalkForwardWindow:
    return WalkForwardWindow(
        window_id=window_id,
        train_start=ts_at(train_start_h),
        train_end=ts_at(train_end_h),
        test_start=ts_at(test_start_h),
        test_end=ts_at(test_end_h),
    )


def noisy_zigzag(n: int = 200, seed: int = 42) -> list[fgt.Candle]:
    """Same wandering-series shape used by test_signal_runner.py, just a
    longer run (200 bars) so it spans enough signals to fill 2+ windows."""
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


# --- run_window ---


def test_run_window_returns_no_metrics_when_test_end_before_any_candle():
    candles = noisy_zigzag()
    w = window(0, -20, -10, -10, -5)  # entirely before candle 0's timestamp
    result = rv.run_window(w, candles, funding_events=[], max_holding_bars=20)
    assert result.signal_count == 0
    assert result.trade_count == 0
    assert result.metrics is None


def test_run_window_only_counts_signals_inside_the_test_range():
    # signals from noisy_zigzag(seed=42) confirm at indices
    # [32,47,62,81,95,107,122,137,156,167,182,197] -- window [80,140)
    # should keep exactly the 5 inside that range (81,95,107,122,137),
    # not the ones from [0,80) used as warmup/train context.
    candles = noisy_zigzag()
    w = window(0, 0, 80, 80, 140)
    result = rv.run_window(w, candles, funding_events=[], max_holding_bars=20)
    assert result.signal_count == 5


def test_run_window_produces_metrics_when_trades_resolve():
    candles = noisy_zigzag()
    w = window(0, 0, 80, 80, 140)
    result = rv.run_window(w, candles, funding_events=[], max_holding_bars=20)
    assert result.metrics is not None
    assert result.metrics.trade_count > 0


def test_run_window_metrics_none_when_every_trade_censored():
    # test window right at the tail of the 200-candle series -- the one
    # signal in range (idx=197) has only 2 forward candles available,
    # nowhere near max_holding_bars=20, so its trade is censored and
    # excluded, leaving zero non-censored trades to compute metrics from.
    candles = noisy_zigzag()
    w = window(2, 0, 195, 195, 200)
    result = rv.run_window(w, candles, funding_events=[], max_holding_bars=20)
    assert result.signal_count == 1
    assert result.trade_count == 1
    assert result.metrics is None


# --- _promotion_pf_stats ---


def _metrics_with_pf_net(pf_net: float | None) -> metrics.MetricsResult:
    return metrics.MetricsResult(
        trade_count=5,
        censored_count=0,
        win_count=3,
        loss_count=2,
        profit_factor_gross=pf_net,
        profit_factor_net=pf_net,
        sharpe_gross=1.0,
        sharpe_net=1.0,
        max_drawdown_pct_gross=0.05,
        max_drawdown_pct_net=0.05,
        avg_holding_duration_hours=10.0,
        trades_per_year=800.0,
    )


def _window_result_with_pf(window_id: int, pf_net: float | None, has_metrics: bool = True) -> rv.WindowResult:
    return rv.WindowResult(
        window=window(window_id, 0, 10, 10, 20),
        signal_count=3,
        trade_count=3,
        metrics=_metrics_with_pf_net(pf_net) if has_metrics else None,
    )


def test_promotion_pf_stats_counts_windows_strictly_above_threshold():
    results = [_window_result_with_pf(0, 1.5), _window_result_with_pf(1, 1.2), _window_result_with_pf(2, 1.31)]
    passing, met = rv._promotion_pf_stats(results, pf_net_threshold=1.3, pf_pass_fraction=2 / 3)
    assert passing == 2  # 1.5 and 1.31 pass; 1.2 does not
    assert met is True  # 2/3 >= 2/3


def test_promotion_pf_stats_window_with_no_metrics_never_passes():
    results = [_window_result_with_pf(0, 1.5), _window_result_with_pf(1, None, has_metrics=False)]
    passing, met = rv._promotion_pf_stats(results, pf_net_threshold=1.3, pf_pass_fraction=0.6667)
    assert passing == 1
    assert met is False  # 1/2 = 0.5 < 0.6667


def test_promotion_pf_stats_zero_windows_never_meets_criterion():
    passing, met = rv._promotion_pf_stats([], pf_net_threshold=1.3, pf_pass_fraction=0.6667)
    assert passing == 0
    assert met is False


def test_promotion_pf_stats_threshold_is_strict_greater_than():
    results = [_window_result_with_pf(0, 1.3)]  # exactly at threshold -- must NOT count as passing
    passing, _ = rv._promotion_pf_stats(results, pf_net_threshold=1.3, pf_pass_fraction=0.01)
    assert passing == 0


# --- run_validation (end-to-end wiring) ---


def test_run_validation_aggregates_across_windows():
    candles = noisy_zigzag()
    windows = [window(0, 0, 80, 80, 140), window(1, 0, 140, 140, 200)]
    result = rv.run_validation(candles, windows, funding_events=[], max_holding_bars=20, pf_net_threshold=1.3, pf_pass_fraction=0.6667)
    assert result.total_windows == 2
    assert len(result.windows) == 2
    assert 0 <= result.windows_passing_pf <= 2


def test_run_validation_empty_windows_list():
    candles = noisy_zigzag()
    result = rv.run_validation(candles, [], funding_events=[], max_holding_bars=20, pf_net_threshold=1.3, pf_pass_fraction=0.6667)
    assert result.total_windows == 0
    assert result.promotion_pf_criterion_met is False


# --- load_config ---


def test_load_config_reads_default_yaml():
    config = rv.load_config()
    assert config["venue"] == "binance"
    assert "walk_forward" in config
    assert config["walk_forward"]["train_months"] > 0
    assert "promotion" in config


# --- default_output_dir ---


def test_default_output_dir_resolves_to_repo_root_docs_not_apps_docs():
    # regression: a previous version used 5 ".." (one too few), silently
    # resolving to apps/docs/validation-results instead of the repo root's
    # docs/validation-results -- caught only by computing this by hand.
    resolved = Path(rv.default_output_dir()).resolve()
    repo_root = Path(__file__).resolve().parents[5]
    assert resolved == repo_root / "docs" / "validation-results"
