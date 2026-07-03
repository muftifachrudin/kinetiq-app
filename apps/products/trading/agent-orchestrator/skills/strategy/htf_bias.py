"""Higher-timeframe (HTF) trend bias -- Fase 2 of the July 2026 validation
roadmap (docs/sonnet5-implementation-roadmap.md), part of the founder's
theory (PRD B.6/2e) never actually tested before this: does the entry
timeframe's signal agree with the trend on Daily/4h (and eventually
Weekly)?

Reuses market_structure.trend_bias() on top of resampled candles --
deliberately NOT a new trend detector, same "one source of truth for what
counts as a swing/trend" principle market_structure.py itself follows for
fib_gann_timing.detect_swings(). resample_candles() is the only new
mechanism this module adds.

Design brief note (deep-dive F9, docs/validation-deep-dive-2026-07.md):
the causally-validated HTF factor found so far was SMA50/200-alignment,
not swing-based trend_bias() -- sma_trend_bias() below exposes that as an
independent candidate signal for Fase 3's fitting to weigh against the
swing-based bias, not blended into htf_alignment_score() here. Blending it
in now would hide it from that decision instead of letting the fit decide
which one (or both) is actually informative.

Like market_structure.py, this is a faktor skor (score contributor), never
a gate -- an opposed HTF bias lowers htf_alignment_score() but never drops
it to 0.0 or blocks a signal outright (docs/fib-gann-validation-brief.md
Section 10's gate-vs-score standing rule).
"""

import datetime

import fib_gann_timing as fgt
import market_structure as ms

# Only 4h/1d resampling is built this round (Fase 2 scope) -- Weekly is
# left out of TIMEFRAME_HOURS on purpose, but DEFAULT_HTF_TIMEFRAME_WEIGHTS
# still carries a "1w" entry so htf_alignment_score()'s present-timeframe
# renormalization (same pattern as fib_gann_timing.confluence_across_
# timeframes()) needs no signature change once Weekly resampling exists --
# just add a "1w" key to the `biases` dict passed in.
TIMEFRAME_HOURS = {"4h": 4, "1d": 24}

# Weekly -> Daily -> 4h, matching the general Weekly>Daily>4h>1h ordering
# fib_gann_timing.DEFAULT_TIMEFRAME_WEIGHTS already uses -- initial numbers
# are free (not yet fit), Fase 3's logistic-regression fitting decides
# which of these actually carries signal.
DEFAULT_HTF_TIMEFRAME_WEIGHTS = {"1w": 0.5, "1d": 0.3, "4h": 0.2}

# Same "penalize heavily, don't hard-block" philosophy and OPPOSED value as
# market_structure.STRUCTURE_ALIGNMENT_SCORE_* -- kept numerically
# consistent across the codebase's alignment-style score contributors.
HTF_ALIGNMENT_SCORE_ALIGNED = 1.0
HTF_ALIGNMENT_SCORE_NEUTRAL = 0.5
HTF_ALIGNMENT_SCORE_OPPOSED = 0.15


def _bucket_start(ts: datetime.datetime, hours: int) -> datetime.datetime:
    """Calendar-aligned UTC bucket start: midnight for 1d, the nearest
    hours-multiple boundary (00/04/08/.../20) for 4h -- not a rolling
    window anchored to the first candle in the input, so results are the
    same regardless of exactly where the input list happens to start."""
    if hours == 24:
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    bucket_hour = (ts.hour // hours) * hours
    return ts.replace(hour=bucket_hour, minute=0, second=0, microsecond=0)


def resample_candles(
    candles: list[fgt.Candle],
    target_timeframe: str,
    as_of: datetime.datetime | None = None,
) -> list[fgt.Candle]:
    """Aggregate 1h candles into `target_timeframe` ("4h" or "1d") OHLCV
    bars, calendar-aligned in UTC. Closed-candle only: a bucket is dropped
    unless the source data reaches all the way to that bucket's own final
    hour -- otherwise a still-forming bucket's high/low/close would be
    read as if the bar had already closed, a lookahead bug hiding inside
    an aggregation step rather than a raw price/time value (the same
    class of bug fib_gann_timing._filter_as_of exists to prevent).

    Only checks against each bucket's OWN latest candle, not a fixed
    expected-count per bucket -- tolerant of the input simply ending
    mid-bucket (the normal, expected case for live/current data) rather
    than raising on it. An internal gap *inside* an otherwise-complete
    bucket (missing an hour in the middle, not at the end) is not detected
    separately here -- that's a data-quality concern for ingestion, not
    this function's no-lookahead guarantee.

    volume is summed, open/close come from the bucket's first/last source
    candle (by ts, not input order), high/low are the bucket's extremes.
    """
    if target_timeframe not in TIMEFRAME_HOURS:
        raise ValueError(f"unsupported target_timeframe: {target_timeframe!r}, expected one of {sorted(TIMEFRAME_HOURS)}")
    if as_of is not None:
        if as_of.tzinfo is None:
            raise ValueError(f"as_of must be timezone-aware (UTC): {as_of!r}")
        candles = [c for c in candles if c.ts <= as_of]
    if not candles:
        return []

    hours = TIMEFRAME_HOURS[target_timeframe]
    bucket_duration = datetime.timedelta(hours=hours)
    source_interval = datetime.timedelta(hours=1)

    buckets: dict[datetime.datetime, list[fgt.Candle]] = {}
    for c in candles:
        buckets.setdefault(_bucket_start(c.ts, hours), []).append(c)

    resampled: list[fgt.Candle] = []
    for bucket_start in sorted(buckets):
        bucket_end = bucket_start + bucket_duration
        bucket_candles = sorted(buckets[bucket_start], key=lambda c: c.ts)
        if bucket_candles[-1].ts < bucket_end - source_interval:
            continue  # this bucket hasn't closed yet -- would need future data
        resampled.append(
            fgt.Candle(
                ts=bucket_start,
                open=bucket_candles[0].open,
                high=max(c.high for c in bucket_candles),
                low=min(c.low for c in bucket_candles),
                close=bucket_candles[-1].close,
                volume=sum(c.volume for c in bucket_candles),
            )
        )
    return resampled


def compute_bias(
    candles_1h: list[fgt.Candle],
    target_timeframe: str,
    as_of: datetime.datetime | None = None,
    atr_period: int = fgt.DEFAULT_ATR_PERIOD,
    atr_multiplier: float = fgt.DEFAULT_ZIGZAG_ATR_MULTIPLIER,
) -> ms.TrendBias:
    """Resample to `target_timeframe`, then reuse market_structure.
    trend_bias() over that resampled series' own swings -- no new trend
    logic. Falls back to TrendBias.UNDEFINED (market_structure's existing
    "not enough evidence" value, not a fabricated read) whenever the
    resampled series doesn't yet have 2 confirmed swings of each type,
    which is the common case for 4h/1d bias early in a backtest window
    where only a few days of 1h data are available so far.
    """
    resampled = resample_candles(candles_1h, target_timeframe, as_of=as_of)
    swings = fgt.detect_swings(resampled, atr_period=atr_period, atr_multiplier=atr_multiplier)
    return ms.trend_bias(swings)


def bias_alignment(direction: fgt.TradeDirection, bias: ms.TrendBias) -> float:
    """Single-timeframe 0-1 alignment score: HTF_ALIGNMENT_SCORE_ALIGNED
    if `bias` agrees with `direction`, _OPPOSED if not, _NEUTRAL if `bias`
    is UNDEFINED. Public (not just an internal helper of
    htf_alignment_score() below) so any OTHER bias source -- e.g.
    sma_trend_bias()'s candidate signal, per Fase 3
    (docs/sonnet5-implementation-roadmap.md) -- can be turned into the
    same comparable 0-1 scale without duplicating this mapping."""
    if bias is ms.TrendBias.UNDEFINED:
        return HTF_ALIGNMENT_SCORE_NEUTRAL
    wants_uptrend = direction is fgt.TradeDirection.LONG
    bias_is_uptrend = bias is ms.TrendBias.UPTREND
    return HTF_ALIGNMENT_SCORE_ALIGNED if wants_uptrend == bias_is_uptrend else HTF_ALIGNMENT_SCORE_OPPOSED


def htf_alignment_score(
    direction: fgt.TradeDirection,
    biases: dict[str, ms.TrendBias],
    weights: dict[str, float] = DEFAULT_HTF_TIMEFRAME_WEIGHTS,
) -> float:
    """0-1 score for fib_gann_timing.score_confluence()'s htf_alignment
    slot: weighted average of per-timeframe alignment against `direction`,
    every trade direction fully agreeing on every present timeframe -> 1.0,
    fully opposed -> HTF_ALIGNMENT_SCORE_OPPOSED (low but never 0 -- a
    faktor skor, not a gate). Missing timeframes in `biases` (e.g. "1w"
    before Weekly resampling exists) are excluded and the remaining
    weights renormalized, same pattern as confluence_across_timeframes(),
    rather than silently scoring a missing timeframe as opposed.

    No timeframes present at all (`biases` empty) -> neutral, not 0 --
    matches the "no signal yet" convention regime_alignment/
    structure_alignment_score already use elsewhere in this codebase.
    """
    present = {tf: w for tf, w in weights.items() if tf in biases}
    total_weight = sum(present.values())
    if total_weight <= 0:
        return HTF_ALIGNMENT_SCORE_NEUTRAL
    weighted_sum = sum(bias_alignment(direction, biases[tf]) * w for tf, w in present.items())
    return weighted_sum / total_weight


def sma_trend_bias(candles: list[fgt.Candle], period: int = 200) -> ms.TrendBias:
    """Simple close-vs-SMA(period) directional proxy -- deep-dive finding
    F9 (docs/validation-deep-dive-2026-07.md) found SMA50/200-alignment to
    be the causally-validated HTF factor in the replication data, distinct
    from (and not necessarily redundant with) swing-based trend_bias().
    Exposed as an independent function here, NOT wired into
    htf_alignment_score() -- Fase 3's fitting is meant to decide which of
    the two (or both) actually carries signal, and folding this in here
    would hide it from that decision.

    Returns TrendBias.UNDEFINED (not a fabricated read) when fewer than
    `period` candles are available -- the same "not enough evidence"
    convention compute_bias()/trend_bias() use.
    """
    if len(candles) < period:
        return ms.TrendBias.UNDEFINED
    sma = sum(c.close for c in candles[-period:]) / period
    last_close = candles[-1].close
    if last_close > sma:
        return ms.TrendBias.UPTREND
    if last_close < sma:
        return ms.TrendBias.DOWNTREND
    return ms.TrendBias.UNDEFINED
