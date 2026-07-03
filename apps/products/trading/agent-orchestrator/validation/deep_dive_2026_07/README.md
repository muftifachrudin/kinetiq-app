# deep_dive_2026_07 — one-off analysis scripts behind the July 2026 deep-dive

Exploratory analysis scripts, NOT production code: no tests, minimal error
handling, cwd-relative file I/O. They exist so every number in
`docs/validation-deep-dive-2026-07.md` (and the investigation memory in
`docs/fable5-crypto-theory-investigation-2026-07.md`) can be reproduced or
re-run on fresh data, not to be imported by anything.

Findings summary lives in those two docs; raw per-window numbers in
`docs/validation-results/replication-2026-07-03.json`. Do not "clean these
up" into the production harness -- anything worth keeping graduates into
`fib_gann_backtest/` with tests (see `docs/sonnet5-implementation-roadmap.md`
phases 1-5 for what actually graduates).

## Requirements

- env: `DATABASE_URL` (Neon; scripts use the HTTP-SQL endpoint because raw
  Postgres connections hang from the Claude Code sandbox), `COINGLASS_API_KEY`
- venv with `pip install -e packages/backtest-core pyyaml` (repo root)
- run everything from one scratch working directory; scripts exchange data
  through files in the cwd

## Run order

1. `python pull_data.py`
   -> `candles_{venue}_{ASSET}.csv` x4 (BTC/ETH x binance/bybit, 1h, 1 year)
2. `python replicate.py binance BTC` (repeat for the other 3 series;
   ~3-5 min each, generate_signals is O(n^2))
   -> `result_{venue}_{ASSET}.json` (per-window metrics + per-trade dump)
3. `python coinglass_pull.py` -> `coinglass_raw.json` (400 daily rows x
   8 endpoints x BTC/ETH; ~2.5s sleep per call for rate limits)
4. `python cg_analysis.py` -> `cg_daily_features.json` + standalone
   fuel/funding/long-short stats printed to stdout
5. `python slices.py` -> replication table, cross-venue Jaccard, pooled
   slices (direction/confidence/session/R:R/holding), CoinGlass join
6. `python implementable.py` -> causal (no-lookahead) filter tests:
   SMA50/200 alignment, prev-day drift, R:R bands, and the combined
   filter, with per-asset/venue/month breakdowns -> `pooled_trades.json`

## Methodological note

`replicate.py` generates signals ONCE over the full series instead of
re-running per walk-forward window like `run_validation.py`. This is
equivalent (the as_of walk is strictly causal, so the signal set at each
bar is identical) except trades near a window's test_end resolve with
later data instead of being censored. Verified against the real CI run
(BTC/Binance: same 2/10 windows passing, same per-window PF pattern).
