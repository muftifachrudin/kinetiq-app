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

import derivatives_context as dc  # noqa: E402
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
    # Fase 3 (docs/sonnet5-implementation-roadmap.md) per-factor dump: the
    # exact 0-1 values score_confluence() weighted-summed into `confidence`
    # above, kept individually so fit_weights.py (or any other future
    # consumer) can fit/inspect each factor's own relationship to trade
    # outcomes instead of only ever seeing the pre-blended final score.
    # structure_alignment and regime_alignment are stored SEPARATELY even
    # though generate_signals() currently feeds score_confluence() the
    # same value for both -- see fit_weights.py's module docstring on why
    # a fitter should treat that as one factor, not two, until they
    # actually diverge (e.g. once market_regime.py, PRD B.6, exists).
    #
    # All seven default to 0.5 (neutral) purely so this stays an ADDITIVE
    # change: existing tests/call sites that construct a Signal directly
    # without caring about these factors (test_shadow_pair.py,
    # test_trade_simulator.py) don't need to be touched. generate_signals()
    # itself always fills in the real computed values below, never these
    # defaults.
    swing_quality: float = 0.5
    fib_gann_confluence: float = 0.5
    volume_confirmation: float = 0.5
    wick_rejection: float = 0.5
    structure_alignment: float = 0.5
    htf_alignment: float = 0.5
    regime_alignment: float = 0.5
    # sma_trend_bias() (htf_bias.py) is a SEPARATE candidate column, not
    # part of the wired confidence formula at all (Fase 2 deliberately
    # left it unblended -- deep-dive F9 found SMA-alignment causally
    # validated, distinct from swing-based trend_bias/htf_alignment
    # above). Same 0-1 alignment convention as htf_alignment
    # (htf_bias.bias_alignment against the signal's own direction), kept
    # here purely so Fase 3's fitting can evaluate it against
    # htf_alignment and let the data decide which one (if either) earns
    # a real weight -- see fit_weights.CANDIDATE_FEATURE_NAMES.
    sma_trend_bias_alignment: float = 0.5
    # Fase 4 (docs/sonnet5-implementation-roadmap.md) derivatives_context.py
    # candidate columns -- same additive discipline as every field above:
    # default to neutral (0.5) / no-event (0.0) so existing Signal(...)
    # call sites that don't pass derivatives_records to generate_signals()
    # (every test written before this round, and any caller with no daily
    # derivatives data available yet) are entirely unaffected.
    # fuel_quadrant is deliberately NOT dumped here at all -- it's context/
    # sizing only (position_sizing.py's high_vol_flag), never a direction
    # feature, per derivatives_context.py's module docstring.
    funding_contrarian_alignment: float = 0.5
    global_ls_contrarian_alignment: float = 0.5
    top_vs_global_alignment: float = 0.5
    liq_cascade_flag: float = 0.0


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
    derivatives_records: list[dc.DailyDerivativesRecord] | None = None,
    max_rr_threshold: float | None = None,
    sl_method: fgt.StopLossMethod = fgt.StopLossMethod.ATR_BUFFER,
) -> list[Signal]:
    """At most one Signal per pivot -- fires on the bar price actually
    TOUCHES a fib/gann line (fib_gann_confluence_score > 0), watching
    every bar after a pivot confirms until that happens (see module
    docstring for why the confirmation bar itself is the wrong trigger).
    A pivot that has already produced a signal is never re-evaluated;
    a pivot whose touch attempts so far have all failed the R:R gate or
    entry validity keeps being watched for a better touch on a later bar,
    until the next reversal makes it no longer the latest pivot.

    derivatives_records (Fase 4, docs/sonnet5-implementation-roadmap.md):
    optional daily CoinGlass+native derivatives history for this signal's
    own coin. When omitted (the default), every derivatives-derived Signal
    field stays at its neutral default -- fully backward compatible with
    every caller that predates Fase 4. When supplied, a day without at
    least 2 prior daily records (series start) also falls back to neutral
    defaults rather than raising, same no-lookahead spirit as
    fib_gann_timing/htf_bias's own early-series handling elsewhere in this
    module.

    max_rr_threshold/sl_method (Fase 5, docs/sonnet5-implementation-
    roadmap.md): both default to the pre-Fase-5 behavior (no upper R:R
    cap, ATR-buffer SL) -- purely additive options for the F5 A/B harness
    (validation/) to sweep, not a change to any existing caller.
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

        # candles[: i + 1], not the full list, for everything below --
        # resample_candles()/swing_quality() have no lookahead of their
        # own, but feeding bars beyond `i` would let a partially-formed
        # *current* HTF bucket, or swing_quality()'s recency component
        # (which divides by len(candles)), see data from later in the
        # backtest than this signal is allowed to know about.
        signal_candles = candles[: i + 1]
        daily_bias = hb.compute_bias(signal_candles, "1d", atr_period=atr_period, atr_multiplier=zigzag_atr_multiplier)
        h4_bias = hb.compute_bias(signal_candles, "4h", atr_period=atr_period, atr_multiplier=zigzag_atr_multiplier)
        htf_score = hb.htf_alignment_score(direction, {"1d": daily_bias, "4h": h4_bias})

        # sma_trend_bias() candidate column (Fase 3) -- NOT wired into
        # confidence at all, purely dumped onto Signal below for
        # fit_weights.py to evaluate against htf_score independently
        # (see htf_bias.py's module docstring / deep-dive F9).
        sma_bias = hb.sma_trend_bias(signal_candles)
        sma_alignment_score = hb.bias_alignment(direction, sma_bias)

        # Fase 3/4 candidate columns -- NOT wired into confidence, purely
        # dumped onto Signal below (see module docstring's derivatives_
        # records param and Signal's own field comments).
        funding_align = global_ls_align = top_vs_global_align = 0.5
        liq_cascade = 0.0
        if derivatives_records is not None:
            try:
                derivatives = dc.compute_derivatives_context(derivatives_records, as_of.date())
            except ValueError:
                derivatives = None  # fewer than 2 prior daily records -- series start, stay neutral
            if derivatives is not None:
                funding_align = dc.funding_contrarian_alignment(direction, derivatives.funding_percentile_365d)
                global_ls_align = dc.global_ls_contrarian_alignment(direction, derivatives.global_ls_percentile_365d)
                top_vs_global_align = dc.top_vs_global_alignment(direction, derivatives.top_vs_global_divergence)
                liq_cascade = 1.0 if derivatives.liq_cascade_flag else 0.0

        confidence = fgt.score_confluence(
            pivot,
            signal_candles,
            fib_confluence=fib_gann_conf,
            regime_alignment=structure_score,
            htf_alignment=htf_score,
            weights=confluence_weights,
        )
        # Fase 3's per-factor dump (Signal.swing_quality/volume_confirmation
        # below) needs these two RAW values individually, but
        # score_confluence() only returns the pre-blended `confidence`
        # total -- so they're recomputed here with the exact same call
        # score_confluence() makes internally, rather than changing that
        # function's public return type for every existing caller/test.
        swing_quality_value = fgt.swing_quality(pivot, signal_candles)
        volume_confirmation_value = min(1.0, fgt.volume_confirmation(pivot, signal_candles) / 2.0)

        entry_price = reference_price
        exit_plan = fgt.build_exit_plan(
            pivot, basis, entry_price, atr_value, gann_prices, extension_levels, sl_atr_buffer_multiplier, sl_method
        )

        if not _entry_is_valid(direction, entry_price, exit_plan.stop_loss):
            continue
        if not fgt.passes_risk_reward_gate(exit_plan, min_rr_threshold, max_rr_threshold):
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
                swing_quality=swing_quality_value,
                fib_gann_confluence=fib_gann_conf,
                volume_confirmation=volume_confirmation_value,
                wick_rejection=pivot.wick_rejection_score,
                structure_alignment=structure_score,
                htf_alignment=htf_score,
                regime_alignment=structure_score,
                sma_trend_bias_alignment=sma_alignment_score,
                funding_contrarian_alignment=funding_align,
                global_ls_contrarian_alignment=global_ls_align,
                top_vs_global_alignment=top_vs_global_align,
                liq_cascade_flag=liq_cascade,
            )
        )

    return signals
