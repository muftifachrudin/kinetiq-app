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

Deliberately single-timeframe for this round -- confluence_across_
timeframes() (weekly/daily/4h/1h, design brief Section 2e) needs aligned
candle series at multiple timeframes simultaneously, which is real
additional complexity (calendar alignment across timeframes, not just
more bars) saved for a later round once single-timeframe wiring is
verified end-to-end. Every score/confidence value here is on a single
timeframe's own 0-1 scale, not yet the final 0-100 cross-timeframe score
PRD B.6 describes.

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
    """One Signal per NEWLY-confirmed pivot that passes the R:R gate --
    NOT one per bar. Once a pivot is the most-recent confirmed swing, it
    stays that way for many subsequent bars (until the next reversal
    confirms); re-evaluating and re-emitting on every one of those bars
    would flood the output with near-duplicates for what is, structurally,
    a single trade decision. A pivot that fails the R:R gate is also
    marked as evaluated (not retried every bar) -- the gate's inputs
    (gann_prices, fib confluence) are keyed off `bar_index`, which does
    change bar-to-bar even for the same pivot, but re-deriving TP/SL from
    the same structural swing over and over isn't a new decision, it's
    the same one restated.
    """
    signals: list[Signal] = []
    last_evaluated_pivot_index: int | None = None
    atr_series = fgt.compute_atr(candles, atr_period)

    for i, candle in enumerate(candles):
        as_of = candle.ts
        swings = fgt.detect_swings(candles, as_of=as_of, atr_period=atr_period, atr_multiplier=zigzag_atr_multiplier)
        if len(swings) < 2:
            continue

        pivot, basis = swings[-1], swings[-2]
        if pivot.index == last_evaluated_pivot_index:
            continue
        last_evaluated_pivot_index = pivot.index

        atr_value = atr_series[i]
        if atr_value is None or atr_value <= 0:
            continue

        gann_prices = fgt.gann_fan_prices(pivot, basis, bar_index=i)
        swing_low = min(pivot.price, basis.price)
        swing_high = max(pivot.price, basis.price)
        fib_levels = fgt.compute_fib_levels(swing_low, swing_high, retracement_levels, extension_levels)
        reference_price = candle.close

        fib_gann_conf = fgt.fib_gann_confluence_score(fib_levels, gann_prices, reference_price, atr_value)

        structure_event = ms.detect_structure_event(swings, reference_price)
        direction = fgt.trade_direction_from_pivot(pivot)
        structure_score = ms.structure_alignment_score(structure_event, direction)

        # candles[: i + 1], not the full list: swing_quality()'s recency
        # component divides by len(candles) -- passing bars beyond `i`
        # would understate recency using data not yet known at this point
        # in the walk, a lookahead bug hiding inside a normalization, not
        # a raw price/time value.
        confidence = fgt.score_confluence(
            pivot, candles[: i + 1], fib_confluence=fib_gann_conf, regime_alignment=structure_score, weights=confluence_weights
        )

        entry_price = reference_price
        exit_plan = fgt.build_exit_plan(
            pivot, basis, entry_price, atr_value, gann_prices, extension_levels, sl_atr_buffer_multiplier
        )

        if not _entry_is_valid(direction, entry_price, exit_plan.stop_loss):
            continue
        if not fgt.passes_risk_reward_gate(exit_plan, min_rr_threshold):
            continue

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
