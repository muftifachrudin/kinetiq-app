import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "validation" / "fib_gann_backtest"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy"))
import metrics  # noqa: E402
import report  # noqa: E402
import run_validation as rv  # noqa: E402
from kinetiq_backtest.types import WalkForwardWindow  # noqa: E402

UTC = datetime.timezone.utc


def ts_at(hours: int) -> datetime.datetime:
    return datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=hours)


def mk_window(window_id: int) -> WalkForwardWindow:
    return WalkForwardWindow(
        window_id=window_id, train_start=ts_at(0), train_end=ts_at(10), test_start=ts_at(10), test_end=ts_at(20)
    )


def mk_metrics(pf_net: float = 1.5) -> metrics.MetricsResult:
    return metrics.MetricsResult(
        trade_count=4,
        censored_count=1,
        win_count=3,
        loss_count=1,
        profit_factor_gross=1.6,
        profit_factor_net=pf_net,
        sharpe_gross=1.2,
        sharpe_net=1.1,
        max_drawdown_pct_gross=0.08,
        max_drawdown_pct_net=0.09,
        avg_holding_duration_hours=12.5,
        trades_per_year=700.0,
    )


def mk_result() -> rv.ValidationRunResult:
    windows = [
        rv.WindowResult(window=mk_window(0), signal_count=5, trade_count=4, metrics=mk_metrics(1.5)),
        rv.WindowResult(window=mk_window(1), signal_count=2, trade_count=2, metrics=None),
    ]
    return rv.ValidationRunResult(
        windows=windows, total_windows=2, windows_passing_pf=1, pf_net_threshold=1.3, pf_pass_fraction=0.6666, promotion_pf_criterion_met=False
    )


# --- to_dict ---


def test_to_dict_top_level_fields():
    d = report.to_dict(mk_result())
    assert d["total_windows"] == 2
    assert d["windows_passing_pf"] == 1
    assert d["promotion_pf_criterion_met"] is False
    assert "not computable yet" in d["promotion_agreement_rate_criterion"]


def test_to_dict_window_with_metrics_serializes_them():
    d = report.to_dict(mk_result())
    assert d["windows"][0]["metrics"]["profit_factor_net"] == 1.5
    assert d["windows"][0]["test_start"] == ts_at(10).isoformat()


def test_to_dict_window_without_metrics_is_none():
    d = report.to_dict(mk_result())
    assert d["windows"][1]["metrics"] is None


def test_to_dict_is_json_serializable():
    d = report.to_dict(mk_result())
    json.dumps(d)  # must not raise


# --- to_markdown ---


def test_to_markdown_contains_summary_and_table():
    md = report.to_markdown(mk_result())
    assert "MET" in md or "NOT MET" in md
    assert "1/2" in md
    assert "n/a" in md  # the window with no metrics renders as n/a, not a crash


# --- write_report ---


def test_write_report_writes_both_files(tmp_path):
    json_path, md_path = report.write_report(mk_result(), str(tmp_path), run_id="test_run")
    assert Path(json_path).exists()
    assert Path(md_path).exists()
    with open(json_path) as f:
        loaded = json.load(f)
    assert loaded["total_windows"] == 2


def test_write_report_creates_output_dir_if_missing(tmp_path):
    output_dir = tmp_path / "nested" / "does_not_exist_yet"
    report.write_report(mk_result(), str(output_dir), run_id="test_run")
    assert output_dir.exists()
