"""Only rows_to_records() (a pure transform) is covered here -- fetch_all_
signals()/main() touch a real DB Session and are (like the rest of this
app's ingestion scripts, per ingest.py/dump_signal_table.py's own
docstrings) verified manually/via a real CI run against a real Neon
branch, not via pytest DB mocking."""

import datetime
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dump_signal_table as dst  # noqa: E402

UTC = datetime.timezone.utc


def mk_row(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=1,
        venue_name="binance",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        ts=datetime.datetime(2026, 1, 1, tzinfo=UTC),
        direction="long",
        entry_price=100.5,
        stop_loss=95.0,
        take_profit_1=110.0,
        confidence=0.75,
        factor_scores={"swing_quality": 0.8},
        created_at=datetime.datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_rows_to_records_maps_every_field():
    records = dst.rows_to_records([mk_row()])
    assert records == [
        {
            "id": 1,
            "venue": "binance",
            "symbol": "BTC/USDT:USDT",
            "timeframe": "1h",
            "ts": "2026-01-01T00:00:00+00:00",
            "direction": "long",
            "entry_price": 100.5,
            "stop_loss": 95.0,
            "take_profit_1": 110.0,
            "confidence": 0.75,
            "factor_scores": {"swing_quality": 0.8},
            "created_at": "2026-01-01T00:01:00+00:00",
        }
    ]


def test_rows_to_records_handles_none_take_profit_1():
    # ExitPlan.take_profits can be empty (Signal model's own docstring) --
    # must stay None, not crash on float(None).
    records = dst.rows_to_records([mk_row(take_profit_1=None)])
    assert records[0]["take_profit_1"] is None


def test_rows_to_records_handles_none_created_at():
    records = dst.rows_to_records([mk_row(created_at=None)])
    assert records[0]["created_at"] is None


def test_rows_to_records_preserves_row_order():
    rows = [mk_row(id=1), mk_row(id=2), mk_row(id=3)]
    records = dst.rows_to_records(rows)
    assert [r["id"] for r in records] == [1, 2, 3]


def test_rows_to_records_empty_list():
    assert dst.rows_to_records([]) == []
