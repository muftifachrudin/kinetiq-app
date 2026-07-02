"""Formalization of the founder's Fib+Gann entry-timing method (docs/prd.md
Section B.6 + the fib_gann_timing validation-harness design brief). Pure
functions over an explicit candle list -- no DB/ccxt coupling, no LangGraph
-- so this module can be called identically from a live signal path and
from a backtest's signal_runner.py (agent-orchestrator/validation/, not
yet built). Every function that walks time takes an `as_of` cutoff and
strictly ignores any candle after it: this is what "no-lookahead" means in
practice, not just a docstring promise -- see _filter_as_of().

Gann Fan is intentionally NOT implemented yet -- price-per-time-unit
calibration was an explicit open design question (the founder's charts use
TradingView's viewport-relative default, which has no fixed backend
equivalent) and is now resolved to "fixed reference scale from the ATR/
swing range used as the pivot basis" (Option 1, confirmed by the founder;
Option 2 -- approximating TradingView's own viewport logic -- was the
alternative, not chosen). Gann computation lands in a follow-up change;
confluence scoring below already accounts for its absence (see
score_confluence's gann_confluence parameter).

Market structure (BOS/CHoCH) is also out of scope here -- noted as an
explicit open item in the design brief, not yet confirmed as part of this
skill's scope vs. a separate skill.
"""

import dataclasses
import datetime
import enum

# Founder's actual Fibonacci levels (confirmed from live chart + settings,
# NOT textbook standard 0.236/0.382/0.5/0.618/0.786 + 1.272/1.618) -- a
# tighter set, especially in the 0.786-1.13 and 1.272-2.272 zones, used for
# more granular target/invalidation precision than the standard spacing
# gives. Callers may override per-instrument; these are the defaults.
DEFAULT_FIB_RETRACEMENT_LEVELS = (0.382, 0.5, 0.618, 0.786, 0.886)
DEFAULT_FIB_EXTENSION_LEVELS = (1.13, 1.272, 1.414, 1.618, 2.0, 2.272, 2.618)

# Weekly -> Daily -> 4h -> 1h, weight decreasing with timeframe size --
# confirmed to match the original PRD B.6 draft exactly, no correction
# needed (unlike the Fib levels above).
DEFAULT_TIMEFRAME_WEIGHTS = {"1w": 0.4, "1d": 0.3, "4h": 0.2, "1h": 0.1}

DEFAULT_ATR_PERIOD = 14
# 1.5-2x ATR(14) starting point per the design brief -- tuned later via
# trader_profile calibration (agreement rate vs trade_annotation), not
# fixed forever.
DEFAULT_ZIGZAG_ATR_MULTIPLIER = 1.75


def _require_utc(value: datetime.datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware (UTC): {value!r}")


@dataclasses.dataclass(frozen=True)
class Candle:
    ts: datetime.datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        _require_utc(self.ts, "Candle.ts")


class SwingDirection(enum.Enum):
    HIGH = "high"
    LOW = "low"


@dataclasses.dataclass(frozen=True)
class SwingPoint:
    index: int  # position in the input candle list this swing was detected from
    ts: datetime.datetime
    price: float
    direction: SwingDirection
    wick_rejection_score: float  # 0-1, see wick_rejection_score()


def _filter_as_of(candles: list[Candle], as_of: datetime.datetime | None) -> list[Candle]:
    """Strict no-lookahead: drop every candle after as_of. Called at the
    top of every public function that walks time, not just once by the
    caller -- so passing the full candle history plus an as_of cutoff is
    always safe, whether this is live or inside a walk-forward backtest."""
    if as_of is None:
        return candles
    _require_utc(as_of, "as_of")
    return [c for c in candles if c.ts <= as_of]


def compute_atr(candles: list[Candle], period: int = DEFAULT_ATR_PERIOD) -> list[float | None]:
    """Wilder's smoothed ATR (TradingView's default ATR method) -- one
    value per candle, None for indices before the first full period is
    available. True range needs the previous candle's close, so index 0 is
    always None regardless of period.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if len(candles) < 2:
        return [None] * len(candles)

    true_ranges: list[float] = [0.0]  # placeholder for index 0, never read
    for i in range(1, len(candles)):
        c, prev = candles[i], candles[i - 1]
        tr = max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close))
        true_ranges.append(tr)

    atr: list[float | None] = [None] * len(candles)
    if len(candles) <= period:
        return atr

    first_atr = sum(true_ranges[1 : period + 1]) / period
    atr[period] = first_atr
    for i in range(period + 1, len(candles)):
        atr[i] = (atr[i - 1] * (period - 1) + true_ranges[i]) / period

    return atr


def wick_rejection_score(candle: Candle, direction: SwingDirection) -> float:
    """0-1: how much of this candle's range is a wick opposite the swing
    direction. A swing LOW with a long lower wick indicates a stop-hunt/
    rejection already played out before the reversal -- the design brief's
    "bonus confidence" case. Returns 0.0 for a zero-range candle (no
    division by zero)."""
    full_range = candle.high - candle.low
    if full_range <= 0:
        return 0.0
    body_low = min(candle.open, candle.close)
    body_high = max(candle.open, candle.close)
    if direction is SwingDirection.LOW:
        wick = body_low - candle.low
    else:
        wick = candle.high - body_high
    return max(0.0, min(1.0, wick / full_range))


def detect_swings(
    candles: list[Candle],
    as_of: datetime.datetime | None = None,
    atr_period: int = DEFAULT_ATR_PERIOD,
    atr_multiplier: float = DEFAULT_ZIGZAG_ATR_MULTIPLIER,
) -> list[SwingPoint]:
    """ZigZag/ATR-based swing detection (design brief Section 3, resolved
    over Fractal-N-bar and manual-visual): a new swing is confirmed once
    price reverses from the current extreme by at least
    atr_multiplier * ATR(period), not on a fixed bar count -- so it scales
    with actual volatility instead of being an easy, uniform target for
    everyone using the same fixed lookback.

    No-lookahead: a swing is only ever confirmed using candles up to and
    including its own index, filtered first by as_of. The threshold ATR
    value used at each step is the ATR at the *current* candle being
    evaluated, never a future one.
    """
    candles = _filter_as_of(candles, as_of)
    if len(candles) < atr_period + 2:
        return []

    atr = compute_atr(candles, atr_period)
    swings: list[SwingPoint] = []

    # Direction is undetermined until the first confirmed reversal -- track
    # both a running highest-high and lowest-low candidate from the start
    # of the series until whichever one triggers a threshold-crossing
    # reversal first; that becomes the first confirmed swing.
    start_idx = atr_period  # first index with a real ATR value
    extreme_high_idx = extreme_low_idx = start_idx
    extreme_high_price = candles[start_idx].high
    extreme_low_price = candles[start_idx].low
    direction: SwingDirection | None = None

    for i in range(start_idx, len(candles)):
        c = candles[i]
        current_atr = atr[i]
        if current_atr is None:
            continue
        threshold = atr_multiplier * current_atr

        # Reversal is checked against the extreme as it stood *before* this
        # candle, then (only if no reversal fired) extended by this candle.
        # Checking against an extreme already-updated-by-this-candle
        # degenerates into comparing a single candle's own high-low range
        # to the threshold -- which trivially trips on every candle of a
        # sustained, purely monotonic move and produces a spurious pivot
        # each time, not a genuine multi-candle reversal. Caught by testing
        # against a synthetic strictly-monotonic decline, which should
        # yield exactly one HIGH and one LOW, not eight alternating pivots.
        if direction is None:
            # undetermined: whichever side trips its threshold first becomes
            # the first confirmed pivot; check HIGH first as a deterministic
            # tie-break on the (rare) candle where both would trip at once.
            if extreme_high_price - c.low >= threshold:
                direction = _confirm_pivot(swings, candles, extreme_high_idx, SwingDirection.HIGH)
                extreme_low_price, extreme_low_idx = c.low, i
                continue
            if c.high - extreme_low_price >= threshold:
                direction = _confirm_pivot(swings, candles, extreme_low_idx, SwingDirection.LOW)
                extreme_high_price, extreme_high_idx = c.high, i
                continue
            if c.high > extreme_high_price:
                extreme_high_price, extreme_high_idx = c.high, i
            if c.low < extreme_low_price:
                extreme_low_price, extreme_low_idx = c.low, i
        elif direction is SwingDirection.HIGH:
            if extreme_high_price - c.low >= threshold:
                direction = _confirm_pivot(swings, candles, extreme_high_idx, SwingDirection.HIGH)
                extreme_low_price, extreme_low_idx = c.low, i
            elif c.high > extreme_high_price:
                extreme_high_price, extreme_high_idx = c.high, i
        elif direction is SwingDirection.LOW:
            if c.high - extreme_low_price >= threshold:
                direction = _confirm_pivot(swings, candles, extreme_low_idx, SwingDirection.LOW)
                extreme_high_price, extreme_high_idx = c.high, i
            elif c.low < extreme_low_price:
                extreme_low_price, extreme_low_idx = c.low, i

    return swings


def _confirm_pivot(
    swings: list[SwingPoint], candles: list[Candle], pivot_idx: int, direction: SwingDirection
) -> SwingDirection:
    """Appends the confirmed pivot and returns the new direction to look
    for next (the opposite of the one just confirmed)."""
    pivot_candle = candles[pivot_idx]
    swings.append(
        SwingPoint(
            index=pivot_idx,
            ts=pivot_candle.ts,
            price=pivot_candle.high if direction is SwingDirection.HIGH else pivot_candle.low,
            direction=direction,
            wick_rejection_score=wick_rejection_score(pivot_candle, direction),
        )
    )
    return SwingDirection.LOW if direction is SwingDirection.HIGH else SwingDirection.HIGH


def compute_fib_levels(
    swing_low: float,
    swing_high: float,
    retracement_levels: tuple[float, ...] = DEFAULT_FIB_RETRACEMENT_LEVELS,
    extension_levels: tuple[float, ...] = DEFAULT_FIB_EXTENSION_LEVELS,
) -> dict[str, dict[float, float]]:
    """Retracement/extension prices for one swing leg. Direction-agnostic:
    caller passes swing_low/swing_high regardless of which one came first
    chronologically -- retracements always measure back from swing_high
    toward swing_low (the standard convention), extensions project beyond
    swing_low in the same direction.
    """
    if swing_high <= swing_low:
        raise ValueError(f"swing_high ({swing_high}) must be greater than swing_low ({swing_low})")

    leg = swing_high - swing_low
    retracements = {level: swing_high - level * leg for level in retracement_levels}
    extensions = {level: swing_high - level * leg for level in extension_levels}
    return {"retracement": retracements, "extension": extensions}


def swing_quality(
    swing: SwingPoint,
    candles: list[Candle],
    atr_period: int = DEFAULT_ATR_PERIOD,
    atr_multiplier: float = DEFAULT_ZIGZAG_ATR_MULTIPLIER,
) -> float:
    """0-1: two equally-weighted components (design brief Section 4):
    displacement of the pivot candle's own true range relative to the ATR-
    scaled threshold that confirmed it (a pivot formed on an unusually
    violent candle is more decisive evidence than one that just barely
    crossed the threshold over several quiet candles), and recency (a
    swing near the end of the series, closer to `as_of`, is more relevant
    to a current entry-timing decision than a stale one further back).
    """
    atr = compute_atr(candles, atr_period)
    if swing.index == 0 or swing.index >= len(atr) or atr[swing.index] is None or atr[swing.index] == 0:
        return 0.0

    pivot, prev = candles[swing.index], candles[swing.index - 1]
    true_range = max(pivot.high - pivot.low, abs(pivot.high - prev.close), abs(pivot.low - prev.close))
    displacement_ratio = min(1.0, true_range / (atr_multiplier * atr[swing.index]))

    recency = (swing.index + 1) / len(candles)
    return 0.5 * displacement_ratio + 0.5 * recency


def volume_confirmation(swing: SwingPoint, candles: list[Candle], lookback: int = 20) -> float:
    """0-1+: the displacement candle's volume vs. the rolling average
    volume of the `lookback` candles before it. A swing formed on
    below-average volume is weaker evidence of real participant
    conviction."""
    if swing.index >= len(candles):
        raise ValueError("swing.index out of range for candles")
    window_start = max(0, swing.index - lookback)
    window = candles[window_start : swing.index]
    if not window:
        return 0.0
    avg_volume = sum(c.volume for c in window) / len(window)
    if avg_volume <= 0:
        return 0.0
    return candles[swing.index].volume / avg_volume


@dataclasses.dataclass(frozen=True)
class ConfluenceWeights:
    swing_quality: float = 0.25
    fib_gann_confluence: float = 0.35
    regime_alignment: float = 0.15
    volume_confirmation: float = 0.15
    wick_rejection: float = 0.10

    def __post_init__(self) -> None:
        total = (
            self.swing_quality
            + self.fib_gann_confluence
            + self.regime_alignment
            + self.volume_confirmation
            + self.wick_rejection
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"ConfluenceWeights must sum to 1.0, got {total}")


def score_confluence(
    swing: SwingPoint,
    candles: list[Candle],
    fib_confluence: float,
    regime_alignment: float | None = None,
    weights: ConfluenceWeights = ConfluenceWeights(),
) -> float:
    """Design brief Section 4's confidence formula:
        confidence = w1*swing_quality + w2*fib_gann_confluence
                   + w3*regime_alignment + w4*volume_confirmation
                   + w5*wick_rejection_score

    fib_confluence is passed in rather than computed here -- it's genuinely
    Fib+Gann overlap per the design brief, but Gann isn't implemented yet
    (see module docstring), so callers currently pass a Fib-only overlap
    score. This function doesn't know or care which; it's a placeholder
    for the caller to fill in correctly once Gann lands, not a silent
    approximation baked into this function.

    regime_alignment defaults to a neutral 1.0 (no penalty, no boost) --
    market_regime.py (PRD B.6) doesn't exist yet, so there's no real
    regime signal to align against. This is an explicit stand-in, not a
    considered "neutral is usually right" judgment call.

    weights are NOT fit from data yet (design brief: should eventually be
    logistic-regression-fit against trade_annotation outcomes, reusing the
    trader_profile calibration pipeline -- B.6b, which itself doesn't
    exist yet since it needs real annotated trade history). The defaults
    above are a reasonable starting point, not a calibrated result.
    """
    if regime_alignment is None:
        regime_alignment = 1.0

    vol_conf = min(1.0, volume_confirmation(swing, candles) / 2.0)  # normalize: 2x avg volume -> full score
    quality = swing_quality(swing, candles)

    return (
        weights.swing_quality * quality
        + weights.fib_gann_confluence * fib_confluence
        + weights.regime_alignment * regime_alignment
        + weights.volume_confirmation * vol_conf
        + weights.wick_rejection * swing.wick_rejection_score
    )


def fib_confluence_score(
    fib_levels: dict[str, dict[float, float]],
    reference_price: float,
    atr_value: float,
) -> float:
    """0-1: how close reference_price sits to the nearest Fib level,
    normalized by ATR (design brief Section 4: overlap > 0.5x ATR should
    NOT count as confluence -- it's coincidence, not a genuine level
    interaction). Returns 0.0 if no level is within that band."""
    if atr_value <= 0:
        return 0.0
    all_prices = list(fib_levels["retracement"].values()) + list(fib_levels["extension"].values())
    if not all_prices:
        return 0.0
    nearest_distance = min(abs(reference_price - p) for p in all_prices)
    band = 0.5 * atr_value
    if nearest_distance >= band:
        return 0.0
    return 1.0 - (nearest_distance / band)


def confluence_across_timeframes(
    scores_by_timeframe: dict[str, float],
    weights: dict[str, float] = DEFAULT_TIMEFRAME_WEIGHTS,
) -> float:
    """Weighted average across timeframes present in scores_by_timeframe,
    scaled to 0-100 for the final entry-timing signal (PRD B.6: "skor
    0-100"). scores_by_timeframe values must each be 0-1 (e.g. the output
    of fib_confluence_score/score_confluence) -- passing already-0-100
    values here double-scales the result silently (no range check is
    possible without also rejecting legitimate values near 1.0).

    Missing timeframes are excluded and the remaining weights
    renormalized, rather than silently treating a missing timeframe as a
    zero score (which would understate confluence just because e.g.
    weekly data isn't available yet for a new listing).
    """
    present = {tf: w for tf, w in weights.items() if tf in scores_by_timeframe}
    total_weight = sum(present.values())
    if total_weight <= 0:
        return 0.0
    weighted_sum = sum(scores_by_timeframe[tf] * w for tf, w in present.items())
    return 100.0 * weighted_sum / total_weight
