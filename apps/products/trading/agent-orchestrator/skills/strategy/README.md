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

## market_structure.py

Smart Money Concept market structure (BOS/CHoCH), design brief Section 2d.
A separate skill from `fib_gann_timing.py` by founder decision (2 Juli
2026) -- it plugs into `fib_gann_timing.score_confluence()`'s
`regime_alignment` slot via `structure_alignment_score()`, the same
pluggable-input pattern `market_regime.py` (not built yet) is meant to
use, rather than being folded into swing detection itself. Built entirely
on top of `fib_gann_timing.detect_swings()`'s output -- no separate pivot
detection logic.
