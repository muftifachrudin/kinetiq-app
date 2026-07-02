# strategy skills

Pure-function strategy logic, no DB/ccxt/LangGraph coupling -- callable
identically from a live signal path and from a backtest's signal_runner.py
(`agent-orchestrator/validation/`, not yet built).

## fib_gann_timing.py

Formalization of the founder's Fib+Gann entry-timing method. See
`docs/prd.md` Section B.6 and `docs/fib-gann-validation-brief.md` for the
design brief this implements.

### Visually validating the Gann Fan calibration

`docs/fib-gann-validation-brief.md` Section 2c requires visual validation
against a real chart before the Gann Fan calibration (`price_per_time_unit =
swing_price_range / swing_duration_in_bars`) is relied on anywhere. This has
**not** been done yet.

Run `scripts/gann_fan_visual_check.py` against real instrument data to get
the exact two anchor points to draw on TradingView, plus this module's
computed price for every Gann angle at a handful of future bars:

```bash
python3 scripts/gann_fan_visual_check.py --venue binance --symbol "BTC/USDT:USDT" --timeframe 1h
```

Draw a Gann Fan on TradingView using the same two anchor points the script
prints, then compare its angle-line prices at the listed bars to the
script's output. They should match within rounding -- if they don't, the
calibration needs revisiting before this is relied on.
