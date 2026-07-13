"""Only parse_entity_flow() is covered here -- fetch_entity_flow() touches
a real HTTP call and is verified manually against the real Arkham API,
same testing discipline as ccxt_generic.py's fetch_* functions."""

import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "connectors", "onchain"))
import arkham  # noqa: E402

UTC = datetime.timezone.utc


def test_parse_entity_flow_flattens_single_chain():
    raw = {
        "bitcoin": [
            {"time": "2026-07-01T00:00:00Z", "inflow": 1000.5, "outflow": 250.0, "cumulativeInflow": 5000.0, "cumulativeOutflow": 2000.0},
        ]
    }
    records = arkham.parse_entity_flow("binance", raw)
    assert records == [
        {
            "source": "arkham",
            "entity": "binance",
            "chain": "bitcoin",
            "ts": datetime.datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC),
            "inflow_usd": 1000.5,
            "outflow_usd": 250.0,
            "cumulative_inflow_usd": 5000.0,
            "cumulative_outflow_usd": 2000.0,
        }
    ]


def test_parse_entity_flow_flattens_multiple_chains_and_points():
    raw = {
        "bitcoin": [
            {"time": "2026-07-01T00:00:00Z", "inflow": 100.0, "outflow": 50.0, "cumulativeInflow": 100.0, "cumulativeOutflow": 50.0},
            {"time": "2026-07-02T00:00:00Z", "inflow": 200.0, "outflow": 75.0, "cumulativeInflow": 300.0, "cumulativeOutflow": 125.0},
        ],
        "ethereum": [
            {"time": "2026-07-01T00:00:00Z", "inflow": 10.0, "outflow": 5.0, "cumulativeInflow": 10.0, "cumulativeOutflow": 5.0},
        ],
    }
    records = arkham.parse_entity_flow("coinbase", raw)
    assert len(records) == 3
    assert {r["chain"] for r in records} == {"bitcoin", "ethereum"}
    assert all(r["entity"] == "coinbase" for r in records)


def test_parse_entity_flow_always_sets_source_explicitly():
    # Regression test: `source` must be set on every record, not left for
    # the DB's server_default to fill in -- db.merge() (ingest_onchain.py)
    # decides INSERT vs UPDATE from the Python-side primary key values
    # before flush, so an unset `source` makes every re-run look like a
    # brand new row and crash with a UniqueViolation on the real composite
    # PK. Caught via an actual second run against real Postgres, not by
    # reading the code.
    raw = {"bitcoin": [{"time": "2026-07-01T00:00:00Z", "inflow": 1.0, "outflow": 1.0, "cumulativeInflow": 1.0, "cumulativeOutflow": 1.0}]}
    records = arkham.parse_entity_flow("binance", raw)
    assert records[0]["source"] == "arkham"


def test_parse_entity_flow_handles_missing_optional_fields():
    raw = {"bitcoin": [{"time": "2026-07-01T00:00:00Z"}]}
    records = arkham.parse_entity_flow("okx", raw)
    assert records[0]["inflow_usd"] is None
    assert records[0]["outflow_usd"] is None
    assert records[0]["cumulative_inflow_usd"] is None
    assert records[0]["cumulative_outflow_usd"] is None


def test_parse_entity_flow_empty_response():
    assert arkham.parse_entity_flow("kraken", {}) == []


def test_parse_entity_flow_naive_timestamp_defaults_to_utc():
    # Defensive case -- Arkham's docs say ISO 8601 with Z, but if a response
    # ever omits the offset, don't silently produce a naive datetime that
    # would break TIMESTAMPTZ insertion semantics later.
    raw = {"bitcoin": [{"time": "2026-07-01T00:00:00", "inflow": 1.0, "outflow": 1.0, "cumulativeInflow": 1.0, "cumulativeOutflow": 1.0}]}
    records = arkham.parse_entity_flow("bybit", raw)
    assert records[0]["ts"].tzinfo is not None
