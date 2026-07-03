# validation

Standalone backtest harness for `fib_gann_timing.py` + `market_structure.py`,
validated head-to-head against MARKOVIZ V5 before promotion to the live
`portfolio_rebalance_graph` path (design brief Section 1 -- kept deliberately
separate from `graphs/` for this reason, no LangGraph coupling here).

## fib_gann_backtest/

- **`signal_runner.py`** -- done. Pure (no DB), walks candles forward with a
  strict `as_of` cutoff, wiring together every skill built so far into one
  signal per pivot: `detect_swings` -> `gann_fan_prices` ->
  `compute_fib_levels` -> `fib_gann_confluence_score` ->
  `market_structure.detect_structure_event` -> `score_confluence` ->
  `build_exit_plan` -> `passes_risk_reward_gate`. Fires on the bar price
  actually TOUCHES a fib/gann line (founder-confirmed entry trigger, 3 Juli
  2026), not on the bar the pivot itself confirms -- a pivot confirms with a
  lag, so the retracement into a level usually happens several bars later;
  see the module's own docstring for the full reasoning. Single-timeframe
  only for now -- `confluence_across_timeframes()` (weekly/daily/4h/1h) needs
  aligned multi-timeframe candle series, saved for a later round.
- **`data_loader.py`** -- done. Loads historical candles from the DB, same
  connection pattern as `apps/products/trading/ingestion/ingest.py`. Not
  covered by pytest (needs a real `DATABASE_URL`, like `ingest.py` itself) --
  verify by running it directly.
- **`trade_simulator.py`** -- done. Wraps
  `fib_gann_timing.label_triple_barrier()` plus direction-adjusted,
  snapshot-based funding-cost deduction (design brief Section 6:
  funding-aware PF/Sharpe is mandatory, not optional) --
  `simulate_trade()`/`simulate_trades()` produce `SimulatedTrade` records
  (`label`, `funding_cost_pct`, `net_return_pct`) that `metrics.py` (still
  not built) will consume. Purely a labeling/measurement layer -- no gate,
  no signal rejection happens here, consistent with the standing
  gate-vs-score principle (`docs/fib-gann-validation-brief.md` Section 10).
  See Section 12 of the validation brief for the full writeup, including a
  real finding: production's `funding_rate` table currently has only 1 row
  for BTC (ingestion has never run at real volume), and CoinGlass's daily
  funding snapshots are too coarse to ever land inside a short (<24h)
  holding window -- funding-cost deduction is code-verified correct via
  synthetic tests, but has no real dense funding data to exercise yet.
- **`trade_simulator.py`'s leverage/liquidation-aware extension** -- done
  (`docs/shadow-simulator-brief.md`, points 1-2). `MarginContext`/
  `build_margin_context()`/`simulate_leveraged_trade()` are ADDITIVE to
  the above (nothing existing changed) -- they model what a real leveraged
  position does that a naive paper simulation doesn't: it can get
  LIQUIDATED before ever reaching the structural SL if initial margin is
  too thin for the leverage used, and funding cost erodes that margin bar
  by bar (a flat-price position can still get liquidated purely from
  funding bleed). `max_safe_leverage()`/`assert_liquidation_safe()`
  enforce a fail-fast invariant (liquidation must sit >= buffer_k*ATR
  beyond the SL) -- exact algebraically, not approximate. 22 new tests
  (157 total), ruff clean. See Section 13 of the validation brief for the
  full design, a real finding (the 3 real signals' `max_safe_leverage`
  comes out 37-58x, which is mathematically valid but far above what's
  actually safe to trade -- an absolute leverage cap is a separate,
  deliberately-not-ML-learned hard rule, not yet implemented), and why
  `initial_margin` is a fraction-of-notional here rather than the
  dollar figure the brief's pseudocode shows.
- **`metrics.py`** -- done. Computes PF/Sharpe/max-drawdown from
  `SimulatedTrade` lists, funding-aware per design brief Section 6: every
  metric is reported BOTH gross (raw price PnL) and net (after funding
  cost) side by side, a big gap between them is itself the diagnostic the
  brief asks for. Sharpe is annualized from each trade's actual holding
  duration (`signal_ts` -> `label.exit_ts`), not an assumed 252 trading
  days -- crypto perps trade 24/7 with non-uniform holding periods.
  Censored trades are excluded from every calculation (same
  right-censoring discipline as the rest of this session).
  `compute_metrics_by_regime()` supports the brief's regime-segmented
  breakdown via a pluggable `regime_of` callable, but this is
  architecturally-supported-not-yet-verified -- `market_regime.py` (PRD
  B.6) doesn't exist, so there's no real regime label to group by yet.
  13 new tests (185 total), ruff clean. Verified against the 3 real
  BTC/USDT signals: PF net 1.16, Sharpe net 1.80 (annualized from an
  actual ~8.3h average holding period), max drawdown 1.47% -- correct
  arithmetic on real data, but n=3 is nowhere near enough for these
  numbers to mean anything statistically; see Section 16 of the
  validation brief.
- **`../configs/walk_forward_windows.yaml` + `run_validation.py` +
  `report.py`** -- done, closing out the last gaps in Section 6.
  `run_validation.py` wires `data_loader.load_candles()` ->
  `generate_windows_by_calendar()` (`packages/backtest-core`) -> per
  window `signal_runner.generate_signals()` ->
  `trade_simulator.simulate_trades()` -> `metrics.compute_metrics()`, and
  checks the design brief Section 7 PF promotion criterion (PF net above
  a threshold in >= a pass-fraction of windows) -- the OTHER promotion
  criterion (agreement rate vs `trade_annotation`) is explicitly reported
  as "not computable yet" rather than silently skipped, since
  `trade_annotation` has no `signal_id` linkage to a specific generated
  signal. Supports `--dry-run` (preview windows, run nothing, write
  nothing). `report.py` dumps a run to `docs/validation-results/` as JSON
  + Markdown, no new DB table. 18 new tests (203 total), ruff clean. A
  real floating-point bug was caught while writing tests: the config's
  `pf_pass_fraction` (a decimal approximation of "4 dari 6") was rounded
  UP to 0.6667, which made exactly-4-of-6-windows-passing fail its own
  criterion (4/6 < 0.6667) -- fixed to 0.6666 (rounded down). Verified
  against real data in two layers: `data_loader.load_candles()` itself
  can't run from this sandbox (the same already-documented constraint --
  raw psycopg hangs here, only Neon's HTTP-SQL endpoint is reachable), so
  that layer is unverified from here same as always; the rest of the
  pipeline (`run_window`/`run_validation`/`report.write_report`) was
  verified end-to-end against the real 100-candle BTC/USDT dataset,
  including the honest finding that the real walk-forward config (1
  month train + 1 month test) produces **zero windows** against
  production's current ~4-day candle history -- not a bug, just not
  enough ingested data yet for a real calendar walk-forward run. See
  Section 17 of the validation brief for the full writeup.

See `docs/fib-gann-validation-brief.md` Section 6 for the full target
structure and `docs/prd.md`'s living status for what's actually done.

## skills/strategy/post_stop_behavior.py

Capability #2 of the "trade journey prediction" roadmap: once a signal's
stop-loss is hit, `classify_post_stop_behavior()` walks forward looking
for whichever happens first -- price closing back through entry
(RETRACE_TO_ENTRY, "pulang ke rumah" -- the thesis was right, just
stopped out prematurely) or closing well past the SL in the same
direction it broke (REVERSAL_CONTINUATION, "tujuan baru arah
berlawanan"), corroborated by `market_structure.detect_structure_event()`
when a real CHoCH/BOS fires in the continuation direction.
`build_post_stop_profile()`/`predict_post_stop_outcome()` turn a history
of classifications into empirical outcome probabilities per direction --
purely informational (gate-vs-score principle), not wired into
`generate_signals()` or `score_confluence()` yet. Verified against the 2
real BTC/USDT signals that hit their SL in this session's dataset: one
classified RETRACE_TO_ENTRY, the other REVERSAL_CONTINUATION with
`structure_confirmed=True` -- and that second case lines up exactly with
the bullish CHoCH already found at pivot idx=91 in an earlier round's
market_structure verification, an independent cross-check that both
modules read the same real data consistently. See Section 15 of the
validation brief for the full writeup.

## skills/strategy/duration_prediction.py

Not part of `fib_gann_backtest/` either, built alongside it: capability #1
of the "trade journey prediction" roadmap (founder request, 3 Juli 2026) --
`build_duration_profile()`/`predict_duration()` aggregate historical
`fib_gann_timing.TripleBarrierLabel` samples into empirical bar-count
percentiles and outcome probabilities, bucketed by (direction, confidence).
Purely informational per the standing gate-vs-score principle
(`docs/fib-gann-validation-brief.md` Section 10) -- it never rejects a
signal, only attaches an estimate. NOT wired into
`signal_runner.generate_signals()` this round -- that needs a historical
resolved-signal dataset, which is `trade_simulator.py`'s job (still not
built, see below). See Section 9/11 of the validation brief for the full
writeup and verification results.

## skills/strategy/level_strength.py

Not part of `fib_gann_backtest/` itself, but built alongside it this round:
a deterministic touch tracker (`detect_level_touches()`) and strength
scorer (`level_strength_score()`) for fib/gann levels, implementing the
founder's "liquidity magnet" theory (rarer touches = stronger, golden
ratio 0.618/1.618 = strongest, bigger timeframe = stronger, a clean BREAK
invalidates a level going forward). Deliberately NOT wired into
`fib_gann_confluence_score()`/`score_confluence()` yet, and NOT yet
fitted to real trade data (same `ConfluenceWeights`-style deterministic-
now/ML-later sequencing) -- see `docs/fib-gann-validation-brief.md`
Section 6a for the full writeup and real-data verification results.
