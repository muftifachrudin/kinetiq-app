import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "strategy" / "scripts"))
import import_binance_position_history as ibph  # noqa: E402

POSITION_HISTORY_CSV = """Symbol,Margin Mode,Position Side,Entry Price,Avg. Close Price,Max Open Interest,Closed Vol.,Closing PNL,Opened,Closed,Status
BTCUSDT,Cross,Long,73645.8,73698.2,0.001,0.001,0.05239999,2026-05-29 18:25:01,2026-05-30 03:35:09,Closed
ETHUSDT,Isolated,Short,1926.51,1889.76,0.092,0.092,-3.381,2026-06-02 23:35:35,2026-06-03 02:34:56,Closed
SOLUSDT,Cross,Long,65.31,64.49,2.76,2.76,-2.2632,2026-06-10 02:05:10,2026-06-10 07:43:52,Open
"""

TRADE_HISTORY_CSV = """Uid,Time,Symbol,Side,Price,Quantity,Amount,Fee,Realized Profit,Buyer,Maker,Trade ID,Order ID
161257460,2026-05-29 18:25:01,BTCUSDT,BUY,73645.8,0.001,73.6458,0.03682290USDT,0,true,false,1,1
161257460,2026-05-30 03:35:09,BTCUSDT,SELL,73698.2,0.001,73.6982,0.03684910USDT,0.05239999,true,false,2,2
161257460,2026-06-02 23:35:35,ETHUSDT,SELL,1926.51,0.092,177.239,0.08862USDT,0,true,false,3,3
161257460,2026-01-01 00:00:00,ETHUSDT,SELL,9999,0.092,9999,999.0USDT,0,true,false,4,4
"""


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content)
    return str(path)


# --- parse_local_ts / to_instrument_symbol ---


def test_parse_local_ts_applies_offset():
    ts = ibph.parse_local_ts("2026-05-29 18:25:01", 7.0)
    assert ts == datetime.datetime(2026, 5, 29, 18, 25, 1, tzinfo=datetime.timezone(datetime.timedelta(hours=7)))


def test_to_instrument_symbol_strips_usdt_suffix():
    assert ibph.to_instrument_symbol("BTCUSDT") == "BTC/USDT:USDT"
    assert ibph.to_instrument_symbol("1000PEPEUSDT") == "1000PEPE/USDT:USDT"


def test_to_instrument_symbol_rejects_non_usdt_symbol():
    with pytest.raises(ValueError, match="USDT-margined"):
        ibph.to_instrument_symbol("BTCBUSD")


# --- parse_position_history ---


def test_parse_position_history_only_keeps_closed_rows(tmp_path):
    path = write(tmp_path, "positions.csv", POSITION_HISTORY_CSV)
    positions = ibph.parse_position_history(path, tz_offset_hours=7.0)
    assert len(positions) == 2  # the "Open" SOLUSDT row is excluded
    assert {p.symbol for p in positions} == {"BTCUSDT", "ETHUSDT"}


def test_parse_position_history_maps_fields_correctly(tmp_path):
    path = write(tmp_path, "positions.csv", POSITION_HISTORY_CSV)
    positions = ibph.parse_position_history(path, tz_offset_hours=7.0)
    btc = next(p for p in positions if p.symbol == "BTCUSDT")
    assert btc.margin_mode == "cross"
    assert btc.action == "long"
    assert btc.entry_price == pytest.approx(73645.8)
    assert btc.exit_price == pytest.approx(73698.2)
    assert btc.row_number == 1

    eth = next(p for p in positions if p.symbol == "ETHUSDT")
    assert eth.margin_mode == "isolated"
    assert eth.action == "short"
    assert eth.row_number == 2


# --- parse_trade_history / sum_fees_for_position ---


def test_parse_trade_history_strips_currency_suffix_from_fee(tmp_path):
    path = write(tmp_path, "trades.csv", TRADE_HISTORY_CSV)
    fills = ibph.parse_trade_history(path, tz_offset_hours=7.0)
    assert fills[0].fee_usd == pytest.approx(0.03682290)


def test_sum_fees_for_position_matches_symbol_and_time_window(tmp_path):
    pos_path = write(tmp_path, "positions.csv", POSITION_HISTORY_CSV)
    trade_path = write(tmp_path, "trades.csv", TRADE_HISTORY_CSV)
    positions = ibph.parse_position_history(pos_path, tz_offset_hours=7.0)
    fills = ibph.parse_trade_history(trade_path, tz_offset_hours=7.0)

    btc = next(p for p in positions if p.symbol == "BTCUSDT")
    fees = ibph.sum_fees_for_position(fills, btc)
    assert fees == pytest.approx(0.03682290 + 0.03684910)


def test_sum_fees_for_position_excludes_fills_outside_window_even_same_symbol(tmp_path):
    # the 4th ETHUSDT fill in the fixture is dated 2026-01-01, long before
    # the ETHUSDT position's [Opened, Closed] window -- must not be counted.
    pos_path = write(tmp_path, "positions.csv", POSITION_HISTORY_CSV)
    trade_path = write(tmp_path, "trades.csv", TRADE_HISTORY_CSV)
    positions = ibph.parse_position_history(pos_path, tz_offset_hours=7.0)
    fills = ibph.parse_trade_history(trade_path, tz_offset_hours=7.0)

    eth = next(p for p in positions if p.symbol == "ETHUSDT")
    fees = ibph.sum_fees_for_position(fills, eth)
    assert fees == pytest.approx(0.08862)  # NOT 999.08862


# --- build_row ---


def test_build_row_leaves_unknown_fields_null_and_notes_provenance():
    position = ibph.ParsedPosition(
        row_number=7,
        symbol="BTCUSDT",
        margin_mode="cross",
        action="long",
        entry_price=100.0,
        exit_price=110.0,
        opened_ts=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        closed_ts=datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc),
        closing_pnl=5.0,
    )
    row = ibph.build_row(position, fees_paid_usd=1.5)
    assert row["leverage"] is None
    assert row["exit_reason_real"] is None
    assert row["funding_paid_usd"] is None
    assert row["fees_paid_usd"] == pytest.approx(1.5)
    assert "row 7" in row["rationale_text"]
    assert "5.0" in row["rationale_text"]


# --- main (dry-run only -- no DATABASE_URL needed) ---


def test_main_dry_run_does_not_touch_the_db(tmp_path, capsys):
    pos_path = write(tmp_path, "positions.csv", POSITION_HISTORY_CSV)
    trade_path = write(tmp_path, "trades.csv", TRADE_HISTORY_CSV)
    exit_code = ibph.main(
        [
            "--dry-run", "--tenant-email", "founder@example.com",
            "--position-history", pos_path, "--trade-history", trade_path, "--tz-offset-hours", "7",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "2 symbols" in out
