"""Smart Money Concept (SMC) market structure: Break of Structure (BOS)
and Change of Character (CHoCH) -- design brief Section 2d.

Founder-confirmed (2 Juli 2026): this is a SEPARATE skill from
fib_gann_timing.py, not folded into swing detection -- its output plugs
into score_confluence()'s regime_alignment-style slot via
structure_alignment_score(), the same pluggable-input pattern
market_regime.py (PRD B.6, not built yet either) is meant to use. Kept
here as an isolated, independently-testable module rather than adding a
BOS/CHoCH-is-a-swing-validity-gate directly inside detect_swings(), which
was the other option the founder considered and didn't pick.

Built entirely on top of fib_gann_timing.detect_swings()'s output -- no
separate swing/pivot detection logic here, one source of truth for what
counts as a swing point. Pure functions, same no-DB/no-ccxt/no-LangGraph
discipline as fib_gann_timing.py.
"""

import dataclasses
import enum

import fib_gann_timing as fgt

# regime_alignment-style scores (see fib_gann_timing.score_confluence's
# docstring: penalize heavily, don't hard-block) -- not 0.0/1.0, matching
# the brief's own philosophy for this kind of alignment input.
STRUCTURE_ALIGNMENT_SCORE_NEUTRAL = 0.5
STRUCTURE_ALIGNMENT_SCORE_ALIGNED = 1.0
STRUCTURE_ALIGNMENT_SCORE_OPPOSED = 0.15


class TrendBias(enum.Enum):
    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    UNDEFINED = "undefined"  # not enough confirmed swings yet, or highs/lows disagree


class StructureBreakDirection(enum.Enum):
    BULLISH = "bullish"  # reference price broke above the most recent swing high
    BEARISH = "bearish"  # reference price broke below the most recent swing low


class StructureEventType(enum.Enum):
    BOS = "bos"      # break direction matches the established trend bias -- continuation
    CHOCH = "choch"  # break direction opposes (or no trend was established) -- potential shift


@dataclasses.dataclass(frozen=True)
class StructureEvent:
    event_type: StructureEventType
    break_direction: StructureBreakDirection
    trend_bias_before: TrendBias
    broken_level: float  # the swing price that reference_price broke past


def trend_bias(swings: list[fgt.SwingPoint]) -> TrendBias:
    """Higher-highs+higher-lows -> UPTREND, lower-highs+lower-lows ->
    DOWNTREND, anything else (fewer than 2 of either type, or highs and
    lows disagreeing) -> UNDEFINED. Uses only the last two swings of each
    type -- deliberately not a longer lookback, since a stale trend read
    from 10 swings ago is exactly the kind of thing a CHoCH is meant to
    override quickly.
    """
    highs = [s for s in swings if s.direction is fgt.SwingDirection.HIGH]
    lows = [s for s in swings if s.direction is fgt.SwingDirection.LOW]
    if len(highs) < 2 or len(lows) < 2:
        return TrendBias.UNDEFINED

    higher_high = highs[-1].price > highs[-2].price
    higher_low = lows[-1].price > lows[-2].price
    lower_high = highs[-1].price < highs[-2].price
    lower_low = lows[-1].price < lows[-2].price

    if higher_high and higher_low:
        return TrendBias.UPTREND
    if lower_high and lower_low:
        return TrendBias.DOWNTREND
    return TrendBias.UNDEFINED


def detect_structure_event(swings: list[fgt.SwingPoint], reference_price: float) -> StructureEvent | None:
    """Design brief Section 2d: CHoCH marks a potential new pivot forming
    (structure shift), BOS confirms continuation after that shift --
    both are just "did reference_price break past the most recent swing
    high/low", classified against the trend_bias() established
    beforehand. Returns None if reference_price is still inside the
    existing high/low range (no break at all) or if there aren't yet
    both a confirmed swing high and low to test against.

    An UNDEFINED trend_bias with a real break is classified as CHoCH,
    not BOS -- there's no established trend for the break to "continue",
    so treating it as a potential character change is the conservative
    read, not an assumption of continuation that was never confirmed.

    No no-lookahead handling here: `swings` and `reference_price` are the
    caller's responsibility to have derived consistently (e.g.
    detect_swings(candles, as_of=cutoff) for swings, and a reference
    price at or before that same cutoff) -- this function is a pure
    comparison, same as fib_confluence_score/fib_gann_confluence_score.
    """
    highs = [s for s in swings if s.direction is fgt.SwingDirection.HIGH]
    lows = [s for s in swings if s.direction is fgt.SwingDirection.LOW]
    if not highs or not lows:
        return None

    recent_high = highs[-1].price
    recent_low = lows[-1].price

    if reference_price > recent_high:
        break_direction = StructureBreakDirection.BULLISH
        broken_level = recent_high
    elif reference_price < recent_low:
        break_direction = StructureBreakDirection.BEARISH
        broken_level = recent_low
    else:
        return None

    bias = trend_bias(swings)
    continues_uptrend = bias is TrendBias.UPTREND and break_direction is StructureBreakDirection.BULLISH
    continues_downtrend = bias is TrendBias.DOWNTREND and break_direction is StructureBreakDirection.BEARISH
    event_type = StructureEventType.BOS if (continues_uptrend or continues_downtrend) else StructureEventType.CHOCH

    return StructureEvent(
        event_type=event_type, break_direction=break_direction, trend_bias_before=bias, broken_level=broken_level
    )


def structure_alignment_score(event: StructureEvent | None, trade_direction: fgt.TradeDirection) -> float:
    """0-1 alignment score for fib_gann_timing.score_confluence()'s
    regime_alignment-style slot -- design brief Section 2d, plugged in as
    a separate skill rather than built into fib_gann_timing.py itself.

    Scores the break DIRECTION against trade_direction, not the BOS/
    CHoCH label: a CHoCH can be exactly what a trade wants (a fresh
    reversal INTO the trade's direction is the textbook trigger for a
    new-trend entry), while a BOS AGAINST the trade direction is bad
    news regardless of its "BOS" label. No event (price still inside the
    existing structure range) is neutral, matching regime_alignment's
    own default-neutral convention when no regime signal exists yet.
    """
    if event is None:
        return STRUCTURE_ALIGNMENT_SCORE_NEUTRAL
    wants_bullish = trade_direction is fgt.TradeDirection.LONG
    break_is_bullish = event.break_direction is StructureBreakDirection.BULLISH
    return STRUCTURE_ALIGNMENT_SCORE_ALIGNED if wants_bullish == break_is_bullish else STRUCTURE_ALIGNMENT_SCORE_OPPOSED
