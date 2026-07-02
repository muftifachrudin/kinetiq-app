# validation

Standalone backtest harness for `fib_gann_timing.py` + `market_structure.py`,
validated head-to-head against MARKOVIZ V5 before promotion to the live
`portfolio_rebalance_graph` path (design brief Section 1 -- kept deliberately
separate from `graphs/` for this reason, no LangGraph coupling here).

## fib_gann_backtest/

- **`signal_runner.py`** -- done. Pure (no DB), walks candles forward with a
  strict `as_of` cutoff, wiring together every skill built so far into one
  signal per newly-confirmed pivot: `detect_swings` -> `gann_fan_prices` ->
  `compute_fib_levels` -> `fib_gann_confluence_score` ->
  `market_structure.detect_structure_event` -> `score_confluence` ->
  `build_exit_plan` -> `passes_risk_reward_gate`. Single-timeframe only for
  now -- `confluence_across_timeframes()` (weekly/daily/4h/1h) needs aligned
  multi-timeframe candle series, saved for a later round.
- **`data_loader.py`** -- done. Loads historical candles from the DB, same
  connection pattern as `apps/products/trading/ingestion/ingest.py`. Not
  covered by pytest (needs a real `DATABASE_URL`, like `ingest.py` itself) --
  verify by running it directly.
- **`trade_simulator.py`, `metrics.py`, `report.py`** -- NOT built yet.
  `trade_simulator.py` will likely wrap `fib_gann_timing.label_triple_barrier()`
  (already implemented) plus funding-cost deduction (design brief Section 6:
  funding-aware PF/Sharpe is mandatory, not optional).
- **`configs/walk_forward_windows.yaml`, `run_validation.py`** -- NOT built
  yet. `run_validation.py` will wire `data_loader` -> `signal_runner` ->
  `trade_simulator` across `packages/backtest-core`'s walk-forward windows.

See `docs/fib-gann-validation-brief.md` Section 6 for the full target
structure and `docs/prd.md`'s living status for what's actually done.
