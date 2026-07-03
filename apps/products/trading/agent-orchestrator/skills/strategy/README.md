# strategy skills

Pure-function strategy logic, no DB/ccxt/LangGraph coupling -- callable
identically from a live signal path and from a backtest's signal_runner.py
(`agent-orchestrator/validation/`, not yet built).

## fib_gann_timing.py

Formalization of the founder's Fib+Gann entry-timing method. See
`docs/prd.md` Section B.6 and `docs/fib-gann-validation-brief.md` for the
design brief this implements.

### Visually validating the Gann Fan calibration

`docs/fib-gann-validation-brief.md` Section 2c required visual validation
against a real chart before the Gann Fan calibration (`price_per_time_unit =
swing_price_range / swing_duration_in_bars`) could be relied on anywhere.
**Done (3 Juli 2026)** -- confirmed against the exact (price, bar)
coordinates TradingView stored for the founder's real Gann Fan drawing;
this formula's rate matched TradingView's own 1x1 line to within 0.5%. See
`docs/prd.md`'s Fase 2 status for the full verification trail.

`scripts/gann_fan_visual_check.py` is still useful for spot-checking a
different instrument/timeframe later -- it pulls real candle data, prints
the exact two anchor points to draw on TradingView, plus this module's
computed price for every Gann angle at a handful of future bars:

```bash
python3 scripts/gann_fan_visual_check.py --venue binance --symbol "BTC/USDT:USDT" --timeframe 1h
```

Draw a Gann Fan on TradingView using the same two anchor points the script
prints, then compare its angle-line prices at the listed bars to the
script's output -- **use the 1x1 line's own color from the Gann Fan tool's
Style settings**, not whatever line looks like the "middle" one visually.
A parallel channel or trendline drawn separately can look similar and is
an easy misread (this happened once already -- see the verification trail
in docs/prd.md).

## position_sizing.py

F7a (`docs/sonnet5-implementation-roadmap.md`), spec in
`docs/margin-mode-brief.md` Section 4. Pure-function pre-execution sizing
skill: `build_pre_trade_card()` turns a signal's `ExitPlan` + the mandate's
risk/leverage settings into a `PreTradeCard` (risk amount, qty, notional,
`leverage_used` capped by both the mandate and `trade_simulator.
max_safe_leverage()`, initial margin, est. liquidation price, SL/TP1
distance in both notional and margin-leveraged percent). Reuses
`trade_simulator.py`'s leverage/liquidation math rather than reimplementing
it. `margin_mode=CROSS` raises `CrossMarginNotImplementedError` (F7b isn't
built yet -- see the brief's Section 1 for why cross needs portfolio state
this per-signal card doesn't have). Does not touch `signal_runner`/any
gate -- purely a downstream presentation+sizing layer.

## derivatives_context.py

F4 (`docs/sonnet5-implementation-roadmap.md`), graduated from
`validation/deep_dive_2026_07/coinglass_pull.py`+`cg_analysis.py`'s one-off
CoinGlass analysis. Pure function over a caller-supplied daily record
history (CoinGlass Hobbyist + native `funding_rate`/`open_interest`, no
API/DB coupling here): `compute_derivatives_context()` returns funding/
global-long-short percentiles, top-vs-global divergence, a liquidation-
cascade flag, and `fuel_quadrant`, all computed strictly from the day
before `target_date` (no-lookahead enforced structurally, not just
documented). `funding_contrarian_alignment()`/`global_ls_contrarian_
alignment()`/`top_vs_global_alignment()` convert three of those into
direction-signed 0-1 scores (fade-the-crowd) for `signal_runner.Signal`'s
per-factor dump; `liq_cascade_flag` stays an unsigned magnitude feature
(no established directional theory for it). `fuel_quadrant` is NEVER fed
into `Signal`/fitting -- it's context/sizing only, consumed via
`position_sizing.py`'s `high_vol_flag`.

## market_structure.py

Smart Money Concept market structure (BOS/CHoCH), design brief Section 2d.
A separate skill from `fib_gann_timing.py` by founder decision (2 Juli
2026) -- it plugs into `fib_gann_timing.score_confluence()`'s
`regime_alignment` slot via `structure_alignment_score()`, the same
pluggable-input pattern `market_regime.py` (not built yet) is meant to
use, rather than being folded into swing detection itself. Built entirely
on top of `fib_gann_timing.detect_swings()`'s output -- no separate pivot
detection logic.
