-- Ongoing partition rollover (docs/prd.md Section B.9 Fase 1).
--
-- Ensures a real time-range partition exists for the current month plus
-- MONTHS_AHEAD months into the future, for every partitioned time-series
-- table (funding_rate, open_interest, price_basis, orderbook_snapshot,
-- liquidation_event, market_sentiment, ohlcv). Calls
-- kinetiq_ensure_month_partition(table, month), created by migration 0004
-- (packages/db/migrations/versions/0004_partition_rollover.py) -- that
-- migration used the same function once to backfill rows that had been
-- sitting in each table's DEFAULT partition since 0001 (nothing had ever
-- rolled DEFAULT forward into real partitions before). This script is the
-- ongoing half: keep creating empty partitions ahead of time so DEFAULT
-- never accumulates real data again.
--
-- Idempotent and safe to re-run any time -- a month that already has a
-- partition is a clean no-op (see the function's own EXISTS check).
--
-- No Inngest yet (docs/prd.md B.1/B.9 gap), so this runs manually or via
-- cron for now, same as apps/products/trading/ingestion's ingest.py:
--   psql "$DATABASE_URL" -f infra/neon/partitioning/rollover.sql
--
-- Recommended cadence: monthly is enough headroom given MONTHS_AHEAD=3
-- below, but running more often costs nothing -- every call past the
-- first for a given month is a no-op.

DO $$
DECLARE
    v_table text;
    v_months_ahead int := 3;
    v_offset int;
BEGIN
    FOREACH v_table IN ARRAY ARRAY[
        'funding_rate', 'open_interest', 'price_basis', 'orderbook_snapshot',
        'liquidation_event', 'market_sentiment', 'ohlcv'
    ]
    LOOP
        FOR v_offset IN 0..v_months_ahead LOOP
            PERFORM kinetiq_ensure_month_partition(
                v_table,
                (date_trunc('month', CURRENT_DATE) + (v_offset || ' month')::interval)::date
            );
        END LOOP;
    END LOOP;
END $$;
