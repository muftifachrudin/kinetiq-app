import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy" / "scripts"))
import log_trade_annotation as lta  # noqa: E402

UTC = datetime.timezone.utc


# --- parse_ts ---


def test_parse_ts_accepts_utc_offset():
    ts = lta.parse_ts("2026-07-03T14:00:00+00:00")
    assert ts == datetime.datetime(2026, 7, 3, 14, 0, 0, tzinfo=UTC)


def test_parse_ts_rejects_naive_datetime():
    with pytest.raises(SystemExit, match="must include a UTC offset"):
        lta.parse_ts("2026-07-03T14:00:00")


def test_parse_ts_accepts_non_utc_offset():
    ts = lta.parse_ts("2026-07-03T14:00:00-05:00")
    assert ts.utcoffset() == datetime.timedelta(hours=-5)


# --- build_parser / build_row ---


def test_build_row_minimal_required_fields_only():
    args = lta.build_parser().parse_args(
        ["--venue", "binance", "--symbol", "BTC/USDT:USDT", "--ts", "2026-07-03T14:00:00+00:00", "--action", "short"]
    )
    row = lta.build_row(args)
    assert row["ts"] == datetime.datetime(2026, 7, 3, 14, 0, 0, tzinfo=UTC)
    assert row["action"] == "short"
    assert row["swing_ref"] is None
    assert row["leverage"] is None
    assert row["margin_mode"] is None


def test_build_row_all_fields_populated():
    args = lta.build_parser().parse_args(
        [
            "--venue", "binance", "--symbol", "BTC/USDT:USDT", "--ts", "2026-07-03T14:00:00+00:00", "--action", "short",
            "--fib-level", "0.618", "--gann-angle", "1x1", "--rationale", "test note",
            "--swing-ref", '{"pivot_price": 60000, "pivot_index": 91}',
            "--leverage", "10", "--margin-mode", "isolated",
            "--entry-fill-price", "60500.5", "--exit-fill-price", "59800.25",
            "--fees-paid-usd", "12.5", "--funding-paid-usd", "1.2",
            "--exit-reason-real", "take_profit",
        ]
    )
    row = lta.build_row(args)
    assert row["fib_level"] == pytest.approx(0.618)
    assert row["gann_angle"] == "1x1"
    assert row["rationale_text"] == "test note"
    assert row["swing_ref"] == {"pivot_price": 60000, "pivot_index": 91}
    assert row["leverage"] == pytest.approx(10.0)
    assert row["margin_mode"] == "isolated"
    assert row["entry_fill_price"] == pytest.approx(60500.5)
    assert row["exit_fill_price"] == pytest.approx(59800.25)
    assert row["fees_paid_usd"] == pytest.approx(12.5)
    assert row["funding_paid_usd"] == pytest.approx(1.2)
    assert row["exit_reason_real"] == "take_profit"


def test_build_parser_rejects_invalid_margin_mode():
    with pytest.raises(SystemExit):
        lta.build_parser().parse_args(
            ["--venue", "b", "--symbol", "s", "--ts", "2026-07-03T14:00:00+00:00", "--action", "short", "--margin-mode", "bogus"]
        )


def test_build_parser_rejects_invalid_exit_reason_real():
    with pytest.raises(SystemExit):
        lta.build_parser().parse_args(
            ["--venue", "b", "--symbol", "s", "--ts", "2026-07-03T14:00:00+00:00", "--action", "short", "--exit-reason-real", "bogus"]
        )


# --- main (dry-run only -- no DATABASE_URL needed) ---


def test_main_dry_run_does_not_touch_the_db(capsys):
    exit_code = lta.main(
        [
            "--dry-run", "--venue", "binance", "--symbol", "BTC/USDT:USDT", "--ts", "2026-07-03T14:00:00+00:00",
            "--action", "short",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "BTC/USDT:USDT" in out
