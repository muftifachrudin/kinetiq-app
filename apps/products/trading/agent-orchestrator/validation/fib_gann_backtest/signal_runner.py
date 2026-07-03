"""Design brief Section 6: signal_runner.py -- calls fib_gann_timing.py
(and market_structure.py) purely, no DB/ccxt coupling, no LangGraph. Same
contract as those modules: takes an explicit candle list in, returns
signals out, so this can be called identically from a backtest
(trade_simulator.py, not yet built) or eventually a live signal path.

Walks forward bar-by-bar with a strict as_of cutoff at each step (no
lookahead -- see fib_gann_timing._filter_as_of's docstring for what that
guarantees), wiring together every skill built so far into one signal:
detect_swings -> gann_fan_prices -> compute_fib_levels ->
fib_gann_confluence_score -> market_structure.detect_structure_event ->
score_confluence -> build_exit_plan -> passes_risk_reward_gate.

Entry trigger (founder-confirmed, 3 Juli 2026): a signal fires on the bar
price actually TOUCHES a fib/gann line (fib_gann_confluence_score > 0),
not on the bar a pivot first confirms. A ZigZag pivot confirms with a
lag -- price has already moved away from it by confirmation time -- so
the retracement back into a fib/gann level the founder actually watches
for entry happens on a LATER bar, sometimes many bars after confirmation.
Checking confluence only once, at the confirmation bar, would miss that
retracement entirely most of the time. This module instead keeps
watching every bar after a pivot confirms (while it remains the latest
pivot) until price touches a line, then evaluates the full signal at
that bar. Multiple touch attempts for the same pivot are allowed -- an
early touch that fails the R:R gate or entry validity doesn't block a
later, better touch of a different line from firing -- but a pivot that
has already produced one signal won't fire again.

Deliberately single-timeframe for entry-signal generation itself --
confluence_across_timeframes() (weekly/daily/4h/1h, design brief Section
2e) needs aligned candle series at multiple timeframes simultaneously,
which is real additional complexity (calendar alignment across
timeframes, not just more bars) saved for a later round once
single-timeframe wiring is verified end-to-end. Every score/confidence
value here is on a single timeframe's own 0-1 scale, not yet the final
0-100 cross-timeframe score PRD B.6 describes.

Fase 2 (docs/sonnet5-implementation-roadmap.md) DOES now bring in a
higher-timeframe factor, but as a score contributor plugged into
score_confluence()'s htf_alignment slot (htf_bias.py), not as a second
generate_signals() entry timeframe -- the entry trigger itself stays
1h-only, only the bias check resamples 1h candles up to Daily/4h.

Performance note: detect_swings() recomputes from scratch on every bar
(O(n) per call), so this walk is O(n^2) overall -- fine for the hundreds
of candles used in validation so far, but a real multi-year backtest
would need an incremental/windowed variant. Not fixed here; premature
optimization for a round that hasn't yet proven the wiring is correct.
"""

import dataclasses
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "strategy"))

import fib_gann_timing as fgt  # noqa: E402
import htf_bias as hb  # noqa: E402
import market_structure as ms  # noqa: E402


@dataclasses.dataclass(frozen=True)
class Signal:
    ts: datetime.datetime
    index: int  # position in the candle list this signal was generated at
    pivot: fgt.SwingPoint
    basis_leg_start: fgt.SwingPoint
    direction: fgt.TradeDirection
    entry_price: float
    exit_plan: fgt.ExitPlan
    confidence: float  # 0-1, single-timeframe score_confluence() output
    structure_event: ms.StructureEvent | None


def _entry_is_valid(direction: fgt.TradeDirection, entry_price: float, stop_loss: float) -> bool:
    """False if entry_price is already on the wrong side of stop_loss --
    i.e. the trade's premise is invalidated before the position would
    even exist. Real-data catch (3 Juli 2026, BTC/USDT 1h): the pivot
    swing is confirmed with a lag (ZigZag can only confirm a reversal
    after price has already moved away from it), so by the time a bar is
    evaluated, price can have already breached the structural SL level
    intrabar -- e.g. a LONG pivot's low broken by a later candle's wick
    even though that candle's close is still above it. Without this
    check, R:R can look artificially excellent, since risk (entry to SL)
    shrinks toward zero exactly as the setup breaks.
    """
    if direction is fgt.TradeDirection.LONG:
        return entry_price > stop_loss
    return entry_price < stop_loss


def generate_signals(
    candles: list[fgt.Candle],
    atr_period: int = fgt.DEFAULT_ATR_PERIOD,
    zigzag_atr_multiplier: float = fgt.DEFAULT_ZIGZAG_ATR_MULTIPLIER,
    sl_atr_buffer_multiplier: float = fgt.DEFAULT_SL_ATR_BUFFER_MULTIPLIER,
    min_rr_threshold: float = fgt.DEFAULT_MIN_RR_THRESHOLD,
    retracement_levels: tuple[float, ...] = fgt.DEFAULT_FIB_RETRACEMENT_LEVELS,
    extension_levels: tuple[float, ...] = fgt.DEFAULT_FIB_EXTENSION_LEVELS,
    confluence_weights: fgt.ConfluenceWeights = fgt.ConfluenceWeights(),
) -> list[Signal]:
    """At most one Signal per pivot -- fires on the bar price actually
    TOUCHES a fib/gann line (fib_gann_confluence_score > 0), watching
    every bar after a pivot confirms until that happens (see module
    docstring for why the confirmation bar itself is the wrong trigger).
    A pivot that has already produced a signal is never re-evaluated;
    a pivot whose touch attempts so far have all failed the R:R gate or
    entry validity keeps being watched for a better touch on a later bar,
    until the next reversal makes it no longer the latest pivot.
    """
    signals: list[Signal] = []
    signaled_pivot_indices: set[int] = set()
    atr_series = fgt.compute_atr(candles, atr_period)

    for i, candle in enumerate(candles):
        as_of = candle.ts
        swings = fgt.detect_swings(candles, as_of=as_of, atr_period=atr_period, atr_multiplier=zigzag_atr_multiplier)
        if len(swings) < 2:
            continue

        pivot, basis = swings[-1], swings[-2]
        if pivot.index in signaled_pivot_indices:
            continue

        atr_value = atr_series[i]
        if atr_value is None or atr_value <= 0:
            continue

        gann_prices = fgt.gann_fan_prices(pivot, basis, bar_index=i)
        swing_low = min(pivot.price, basis.price)
        swing_high = max(pivot.price, basis.price)
        fib_levels = fgt.compute_fib_levels(swing_low, swing_high, retracement_levels, extension_levels)
        reference_price = candle.close

        fib_gann_conf = fgt.fib_gann_confluence_score(fib_levels, gann_prices, reference_price, atr_value)
        if fib_gann_conf <= 0.0:
            continue  # price hasn't touched a fib/gann line on this bar -- keep watching

        structure_event = ms.detect_structure_event(swings, reference_price)
        direction = fgt.trade_direction_from_pivot(pivot)
        structure_score = ms.structure_alignment_score(structure_event, direction)

        # candles[: i + 1], not the full list, here too -- resample_candles()
        # itself has no lookahead (closed-bucket-only), but feeding it bars
        # beyond `i` would let a partially-formed *current* HTF bucket see
        # 1h candles from later in the backtest than this signal is allowed
        # to know about.
        htf_candles = candles[: i + 1]
        daily_bias = hb.compute_bias(htf_candles, "1d", atr_period=atr_period, atr_multiplier=zigzag_atr_multiplier)
        h4_bias = hb.compute_bias(htf_candles, "4h", atr_period=atr_period, atr_multiplier=zigzag_atr_multiplier)
        htf_score = hb.htf_alignment_score(direction, {"1d": daily_bias, "4h": h4_bias})

        # candles[: i + 1], not the full list: swing_quality()'s recency
        # component divides by len(candles) -- passing bars beyond `i`
        # would understate recency using data not yet known at this point
        # in the walk, a lookahead bug hiding inside a normalization, not
        # a raw price/time value.
        confidence = fgt.score_confluence(
            pivot,
            candles[: i + 1],
            fib_confluence=fib_gann_conf,
            regime_alignment=structure_score,
            htf_alignment=htf_score,
            weights=confluence_weights,
        )

        entry_price = reference_price
        exit_plan = fgt.build_exit_plan(
            pivot, basis, entry_price, atr_value, gann_prices, extension_levels, sl_atr_buffer_multiplier
        )

        if not _entry_is_valid(direction, entry_price, exit_plan.stop_loss):
            continue
        if not fgt.passes_risk_reward_gate(exit_plan, min_rr_threshold):
            continue

        signaled_pivot_indices.add(pivot.index)
        signals.append(
            Signal(
                ts=as_of,
                index=i,
                pivot=pivot,
                basis_leg_start=basis,
                direction=direction,
                entry_price=entry_price,
                exit_plan=exit_plan,
                confidence=confidence,
                structure_event=structure_event,
            )
        )

    return signals
