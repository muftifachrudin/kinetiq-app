"""Founder theory (3 Juli 2026): a fib/gann price level's strength as
support/resistance is not fixed -- it scales with the timeframe it's
drawn on, how rarely it's been tested ("liquidity magnet": an untested
level draws price in and holds, a well-tested one eventually gives way),
and the level's own ratio -- 0.618/1.618 (the golden ratio) is the
founder's stated strongest fib S/R level, stronger than the others.

Two pieces: detect_level_touches() walks a candle series looking for bars
where price actually trades through a given level, and classifies each
touch as a BOUNCE (price closed back away from the level) or a BREAK
(price closed decisively through it) by watching a fixed number of
forward bars -- this is what makes the "kaya dengan data" (rich with
data) touch history the founder described. level_strength_score() then
turns that touch history into a single deterministic number.

Deliberately NOT wired into fib_gann_timing.fib_gann_confluence_score()
or score_confluence() yet -- ConfluenceWeights' 5 named factors already
sum to a fixed 1.0, and how a 6th signal should fold into that existing
formula (a new weight? modifying fib_gann_confluence itself? something
else?) is a separate design decision for a later round, not assumed
here. Deterministic formula, not fitted -- same "reasonable starting
point, not a calibrated result" caveat fib_gann_timing.ConfluenceWeights'
own docstring already carries.

Scoped to STATIC levels (fib retracement/extension) for this round --
Gann angle levels move every bar (a line, not a fixed price), so "how
many times has this level been touched" needs a per-bar price lookup
rather than one fixed float. detect_level_touches() actually supports
that already (level_price_at is a callable, not a bare float), but it
hasn't been exercised or verified against a moving Gann line yet -- only
against real BTC/USDT fib retracement/extension levels. Flagged here so
a future round doesn't assume Gann touch-tracking is validated when it
isn't.
"""

import dataclasses
import datetime
import enum
from collections.abc import Callable

import fib_gann_timing as fgt

# Founder-confirmed (3 Juli 2026): 0.618 (and its extension counterpart
# 1.618) is the strongest fib support/resistance ratio -- the golden
# ratio. Every other ratio gets a neutral base weight; this bonus is
# stated founder domain knowledge, not derived from anything else here.
GOLDEN_RATIO_LEVELS = (0.618, 1.618)
GOLDEN_RATIO_BASE_WEIGHT = 1.5
DEFAULT_BASE_WEIGHT = 1.0

# A level that has already broken once is generally considered
# invalidated as that original S/R -- a single clean break is a much
# stronger signal than several inconclusive pokes, so this discounts
# harder than touch-count decay alone would.
ALREADY_BROKEN_PENALTY = 0.2

DEFAULT_MAX_RESOLUTION_BARS = 10
DEFAULT_OUTCOME_ATR_BUFFER_MULTIPLIER = 0.25


class ApproachDirection(enum.Enum):
    FROM_ABOVE = "from_above"  # level acting as potential support
    FROM_BELOW = "from_below"  # level acting as potential resistance


class TouchOutcome(enum.Enum):
    BOUNCE = "bounce"
    BREAK = "break"
    CENSORED = "censored"


@dataclasses.dataclass(frozen=True)
class LevelTouch:
    level_key: str
    level_price: float
    touch_index: int
    touch_ts: datetime.datetime
    approach: ApproachDirection
    outcome: TouchOutcome
    resolved_index: int | None
    prior_touch_count: int  # how many times this level_key was touched before this one
    # True only when outcome is CENSORED because candles ran out before
    # max_resolution_bars elapsed -- a right-censored sample (outcome
    # unknown), not a genuine "sat in the buffer zone for the full
    # window" case. Same distinction fib_gann_timing.label_triple_
    # barrier()'s own `censored` field makes, for the same reason.
    censored: bool


def detect_level_touches(
    candles: list[fgt.Candle],
    level_price_at: Callable[[int], float],
    level_key: str,
    atr_series: list[float | None],
    start_index: int = 0,
    max_resolution_bars: int = DEFAULT_MAX_RESOLUTION_BARS,
    outcome_atr_buffer_multiplier: float = DEFAULT_OUTCOME_ATR_BUFFER_MULTIPLIER,
) -> list[LevelTouch]:
    """Walks candles[start_index:], recording every bar where price
    actually trades through level_price_at(i) (candle low <= level <=
    candle high -- level_price_at is a callable rather than a bare float
    so a moving Gann line could, in principle, be tracked the same way
    as a fixed fib level; see module docstring for why that path isn't
    verified yet). Each touch is then classified by watching up to
    max_resolution_bars forward candles for a decisive close on one side
    of the level (outcome_atr_buffer_multiplier * ATR beyond it):
    BOUNCE if price closes back away from the level (S/R held), BREAK if
    it closes through in the direction it was already testing.

    Approach direction (which side counts as "away" vs "through") is
    read from the touching candle's own open relative to the level:
    open >= level means price was coming from above (testing it as
    support), open < level means testing it as resistance.
    """
    touches: list[LevelTouch] = []
    touch_count = 0

    for i in range(start_index, len(candles)):
        candle = candles[i]
        level_price = level_price_at(i)
        if not (candle.low <= level_price <= candle.high):
            continue

        atr_value = atr_series[i]
        if atr_value is None or atr_value <= 0:
            continue

        approach = ApproachDirection.FROM_ABOVE if candle.open >= level_price else ApproachDirection.FROM_BELOW
        buffer = outcome_atr_buffer_multiplier * atr_value

        outcome = TouchOutcome.CENSORED
        resolved_index = None
        window_end = min(i + 1 + max_resolution_bars, len(candles))
        for j in range(i + 1, window_end):
            close_j = candles[j].close
            if approach is ApproachDirection.FROM_ABOVE:
                if close_j >= level_price + buffer:
                    outcome, resolved_index = TouchOutcome.BOUNCE, j
                    break
                if close_j <= level_price - buffer:
                    outcome, resolved_index = TouchOutcome.BREAK, j
                    break
            else:
                if close_j <= level_price - buffer:
                    outcome, resolved_index = TouchOutcome.BOUNCE, j
                    break
                if close_j >= level_price + buffer:
                    outcome, resolved_index = TouchOutcome.BREAK, j
                    break

        censored = outcome is TouchOutcome.CENSORED and (len(candles) - (i + 1)) < max_resolution_bars

        touches.append(
            LevelTouch(
                level_key=level_key,
                level_price=level_price,
                touch_index=i,
                touch_ts=candle.ts,
                approach=approach,
                outcome=outcome,
                resolved_index=resolved_index,
                prior_touch_count=touch_count,
                censored=censored,
            )
        )
        touch_count += 1

    return touches


def level_strength_score(
    touches_so_far: list[LevelTouch],
    timeframe: str,
    level_ratio: float | None = None,
    timeframe_weights: dict[str, float] = fgt.DEFAULT_TIMEFRAME_WEIGHTS,
) -> float:
    """Design theory (founder, 3 Juli 2026): scores the LAST touch in
    touches_so_far (all touches for one level_key, oldest first, up to
    and including the one being scored) by combining:
      - timeframe weight -- reuses fib_gann_timing.DEFAULT_TIMEFRAME_
        WEIGHTS as-is (weekly heaviest, 1h lightest), the same weighting
        confluence_across_timeframes() already uses, rather than
        inventing a second scale for the same idea.
      - freshness -- 1 / (prior_touch_count + 1): a never-before-tested
        level scores 1.0, each additional touch erodes it further.
      - golden ratio bonus -- level_ratio in {0.618, 1.618} scores
        GOLDEN_RATIO_BASE_WEIGHT instead of DEFAULT_BASE_WEIGHT.
        level_ratio is None for non-fib levels (e.g. Gann angles), which
        get the neutral base weight -- no golden-ratio-equivalent claim
        has been made for Gann angles, so none is assumed here.
      - already-broken penalty -- if any EARLIER touch in touches_so_far
        resolved as BREAK, the level is treated as invalidated S/R and
        heavily discounted regardless of how fresh or golden it is.
    """
    if not touches_so_far:
        raise ValueError("touches_so_far must not be empty")

    latest = touches_so_far[-1]
    tf_weight = timeframe_weights.get(timeframe, min(timeframe_weights.values()))
    ratio_weight = GOLDEN_RATIO_BASE_WEIGHT if level_ratio in GOLDEN_RATIO_LEVELS else DEFAULT_BASE_WEIGHT
    freshness = 1.0 / (latest.prior_touch_count + 1)
    already_broken = any(t.outcome is TouchOutcome.BREAK for t in touches_so_far[:-1])
    broken_penalty = ALREADY_BROKEN_PENALTY if already_broken else 1.0

    return tf_weight * ratio_weight * freshness * broken_penalty
