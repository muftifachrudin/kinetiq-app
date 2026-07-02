"""Founder theory (3 Juli 2026): after a signal's stop-loss is hit,
price does one of two genuinely different things, and the agent should
be able to tell them apart -- capability #2 of the "trade journey
prediction" roadmap (docs/fib-gann-validation-brief.md Section 9):

- "pulang ke rumah" (RETRACE_TO_ENTRY): price closes back through the
  original entry price -- the directional thesis was basically right,
  the trade was just stopped out prematurely by noise.
- "tujuan baru arah berlawanan" (REVERSAL_CONTINUATION): price keeps
  moving in the SL-breaking direction well past the SL itself -- a real
  reversal, the start of a new opposite-direction move.

Two pieces, same deterministic-now/ML-later sequencing as level_strength.py
and duration_prediction.py: classify_post_stop_behavior() walks forward
from the SL-hit bar and classifies which of the two happened first (or
CHOP if neither did within the window), and
build_post_stop_profile()/predict_post_stop_outcome() turn a history of
those classifications into empirical outcome probabilities per direction.

Per the standing gate-vs-score principle (Section 10): this is
INFORMATIONAL ONLY. Nothing here rejects a signal or blocks a trade --
predict_post_stop_outcome() returns a probability estimate a caller could
attach to a signal's confidence, exactly like duration_prediction's
estimate, never a filter.

Reuses market_structure.detect_structure_event() as corroborating
evidence for REVERSAL_CONTINUATION (the founder's own suggestion: "ada
tidak... CHoCH detector yang udah ada"), rather than relying on price
distance alone -- a continuation confirmed by both a price move AND a
structure break in the same direction is a stronger claim than either
signal on its own, though structure_confirmed is recorded as evidence,
not a second gate (a continuation without structure confirmation is
still classified REVERSAL_CONTINUATION, just noted as weaker).
"""

import dataclasses
import enum

import fib_gann_timing as fgt
import market_structure as ms

DEFAULT_MAX_LOOKFORWARD_BARS = 10
# Same "buffer_k"-style default as trade_simulator.py's liquidation buffer
# and level_strength.py's outcome buffer -- a starting point, not fitted.
DEFAULT_CONTINUATION_ATR_MULTIPLIER = 1.0


class PostStopOutcome(enum.Enum):
    RETRACE_TO_ENTRY = "retrace_to_entry"
    REVERSAL_CONTINUATION = "reversal_continuation"
    CHOP = "chop"  # neither happened within the lookforward window


@dataclasses.dataclass(frozen=True)
class PostStopClassification:
    outcome: PostStopOutcome
    resolved_index: int | None  # absolute index in the input candle list; None for CHOP
    resolved_price: float | None
    bars_to_resolution: int | None
    structure_confirmed: bool  # a CHoCH/BOS in the continuation direction also fired -- only meaningful for REVERSAL_CONTINUATION
    # True only when outcome is CHOP because candles ran out before
    # max_lookforward_bars elapsed -- right-censored (unknown what
    # would've happened next), not a genuine "sat inconclusive for the
    # full window" case. Same distinction every other module in this
    # session's censored field makes.
    censored: bool


def _continuation_break_direction(direction: fgt.TradeDirection) -> ms.StructureBreakDirection:
    # A LONG stopped out and continuing DOWN is a BEARISH break; a SHORT
    # stopped out and continuing UP is a BULLISH break.
    return ms.StructureBreakDirection.BEARISH if direction is fgt.TradeDirection.LONG else ms.StructureBreakDirection.BULLISH


def classify_post_stop_behavior(
    candles: list[fgt.Candle],
    sl_hit_index: int,
    direction: fgt.TradeDirection,
    entry_price: float,
    stop_loss: float,
    atr_series: list[float | None],
    max_lookforward_bars: int = DEFAULT_MAX_LOOKFORWARD_BARS,
    continuation_atr_multiplier: float = DEFAULT_CONTINUATION_ATR_MULTIPLIER,
) -> PostStopClassification:
    """Walks candles[sl_hit_index + 1 : ...] looking for whichever
    happens FIRST: a close back through entry_price (RETRACE_TO_ENTRY) or
    a close beyond stop_loss by continuation_atr_multiplier * ATR in the
    SL-breaking direction (REVERSAL_CONTINUATION). These two thresholds
    sit on strictly opposite sides of stop_loss from entry_price, so a
    single candle's close can never satisfy both -- no same-candle
    tie-break rule is needed here, unlike TP/SL in label_triple_barrier().
    """
    if not candles:
        raise ValueError("candles must not be empty")
    if max_lookforward_bars <= 0:
        raise ValueError("max_lookforward_bars must be positive")

    start_index = sl_hit_index + 1
    window_end = min(start_index + max_lookforward_bars, len(candles))

    for i in range(start_index, window_end):
        candle = candles[i]
        atr_value = atr_series[i]

        retrace_hit = candle.close >= entry_price if direction is fgt.TradeDirection.LONG else candle.close <= entry_price

        continuation_hit = False
        if atr_value is not None and atr_value > 0:
            buffer = continuation_atr_multiplier * atr_value
            if direction is fgt.TradeDirection.LONG:
                continuation_hit = candle.close <= stop_loss - buffer
            else:
                continuation_hit = candle.close >= stop_loss + buffer

        if retrace_hit:
            return PostStopClassification(
                outcome=PostStopOutcome.RETRACE_TO_ENTRY,
                resolved_index=i,
                resolved_price=candle.close,
                bars_to_resolution=i - start_index + 1,
                structure_confirmed=False,
                censored=False,
            )
        if continuation_hit:
            swings = fgt.detect_swings(candles, as_of=candle.ts)
            structure_event = ms.detect_structure_event(swings, reference_price=candle.close)
            structure_confirmed = structure_event is not None and structure_event.break_direction is _continuation_break_direction(
                direction
            )
            return PostStopClassification(
                outcome=PostStopOutcome.REVERSAL_CONTINUATION,
                resolved_index=i,
                resolved_price=candle.close,
                bars_to_resolution=i - start_index + 1,
                structure_confirmed=structure_confirmed,
                censored=False,
            )

    censored = (len(candles) - start_index) < max_lookforward_bars
    return PostStopClassification(
        outcome=PostStopOutcome.CHOP,
        resolved_index=None,
        resolved_price=None,
        bars_to_resolution=None,
        structure_confirmed=False,
        censored=censored,
    )


@dataclasses.dataclass(frozen=True)
class PostStopSample:
    outcome: PostStopOutcome
    direction: fgt.TradeDirection
    censored: bool


@dataclasses.dataclass(frozen=True)
class PostStopProfile:
    samples: tuple[PostStopSample, ...]


def build_post_stop_profile(samples: list[PostStopSample]) -> PostStopProfile:
    if not samples:
        raise ValueError("samples must not be empty")
    return PostStopProfile(samples=tuple(samples))


@dataclasses.dataclass(frozen=True)
class PostStopOutcomeEstimate:
    sample_count: int
    outcome_probabilities: dict[PostStopOutcome, float]  # empirical P(outcome), sums to 1.0 when sample_count > 0


def predict_post_stop_outcome(profile: PostStopProfile, direction: fgt.TradeDirection) -> PostStopOutcomeEstimate:
    """Bucketed by direction only for this round -- deliberately simpler
    than duration_prediction.predict_duration()'s direction+confidence
    bucketing, since there isn't yet enough real sample volume to justify
    a finer split (same discipline as level_strength.py not inventing a
    confidence bucket for Gann angle levels before any data exists for
    them). Finer bucketing is a natural later addition once real
    trade_annotation volume (docs/shadow-simulator-brief.md) exists to
    support it."""
    matching = [s for s in profile.samples if s.direction is direction and not s.censored]
    if not matching:
        return PostStopOutcomeEstimate(sample_count=0, outcome_probabilities={})

    total = len(matching)
    counts: dict[PostStopOutcome, int] = {}
    for s in matching:
        counts[s.outcome] = counts.get(s.outcome, 0) + 1
    return PostStopOutcomeEstimate(sample_count=total, outcome_probabilities={outcome: count / total for outcome, count in counts.items()})
